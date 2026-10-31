from datetime import date, time, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from unittest import skipUnless
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction, connection, connections, close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings, Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import facilities as service, memberships
from .models import ClubFacility, ShootingArea, FacilityPhoto, FacilityPhotoUpload, ClubRoleAssignment
from .test_memberships import Fixtures
from .tests import login_with_mfa


class FacilityFixtures(Fixtures):
    def setUp(self):
        super().setUp()
        self.visitor = AnonymousUser()
        self.facility = service.save(self.admin, self.club.pk, "facility", dict(name="Synthetic range", timezone="Europe/Dublin",
            audience="public", location_audience="admins", address="PRIVATE EXACT ADDRESS", latitude="53.123456", longitude="-6.123456"))
        self.area = service.save(self.admin, self.club.pk, "area", dict(name="Synthetic outdoor line", kind="outdoor",
            disciplines=["recurve", "barebow"], distances_m=[18, 30, 70], lane_capacity=8, target_capacity=4, audience="public"), parent_id=self.facility.pk)

    def rule(self, **changes):
        data = dict(weekday=5, starts_on=date(2026, 1, 1), ends_on=None, start_time=time(9), end_time=time(12), priority=0, audience="public")
        data.update(changes)
        return service.save(self.admin, self.club.pk, "rule", data, parent_id=self.area.pk)

    def exception(self, **changes):
        data = dict(starts_on=date(2026, 5, 2), ends_on=date(2026, 5, 2), kind="closed", replacement_slots=[],
            priority=0, audience="public", reason="Synthetic holiday closure")
        data.update(changes)
        return service.save(self.admin, self.club.pk, "exception", data, parent_id=self.area.pk)

    def calendar(self, day, actor=None):
        return service.calendar(actor or self.visitor, self.area.pk, day, 1)["days"][0]


@override_settings(CLUBS_ENABLED=True, CLUB_MEMBERSHIPS_ENABLED=True, CLUB_FACILITIES_ENABLED=True)
class FacilityTests(FacilityFixtures, TestCase):
    def test_public_location_redaction_in_html_and_json(self):
        url = reverse("clubs:facility", args=[self.facility.pk])
        for response in (self.client.get(url), self.client.get(url, {"format": "json"}),
                self.client.get(reverse("clubs:facilities", args=[self.club.pk]), {"format": "json"})):
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "PRIVATE EXACT ADDRESS")
            self.assertNotContains(response, "53.123456")
            self.assertNotContains(response, "-6.123456")
            self.assertIn("no-store", response["Cache-Control"])
        payload = service.detail(self.visitor, self.facility.pk)
        self.assertNotIn("latitude", payload)
        self.assertEqual(service.detail(self.admin, self.facility.pk)["address"], "PRIVATE EXACT ADDRESS")

    def test_location_audience_can_be_broader_but_never_bypasses_facility(self):
        service.save(self.admin, self.club.pk, "facility", {"audience": "members", "location_audience": "public"},
            object_id=self.facility.pk, version=self.facility.version)
        with self.assertRaises(service.Http404):
            service.detail(self.visitor, self.facility.pk)
        self.join()
        self.assertEqual(service.detail(self.member, self.facility.pk)["address"], "PRIVATE EXACT ADDRESS")

    def test_private_club_never_exposed_to_nonmembers(self):
        private = service.save(self.admin, self.private.pk, "facility", {"name": "Hidden venue", "audience": "public", "location_audience": "public", "address": "Secret"})
        for actor in (self.visitor, self.other):
            with self.assertRaises(service.Http404):
                service.detail(actor, private.pk)
        invite, token = memberships.invite(self.admin, self.private.pk, self.member.email)
        memberships.accept_invite(self.member, invite.pk, token)
        self.assertEqual(service.detail(self.member, private.pk)["name"], "Hidden venue")

    def test_guardian_representation_rechecked_without_parent_membership(self):
        self.join(self.parent, athlete=self.child)
        service.save(self.admin, self.club.pk, "facility", {"audience": "members"}, object_id=self.facility.pk, version=self.facility.version)
        self.assertEqual(service.detail(self.parent, self.facility.pk)["name"], self.facility.name)
        self.child.birth_date = date(2000, 1, 1)
        self.child.save()
        with self.assertRaises(service.Http404):
            service.detail(self.parent, self.facility.pk)

    def test_coach_area_requires_current_club_role(self):
        service.save(self.admin, self.club.pk, "area", {"audience": "coaches"}, object_id=self.area.pk, version=self.area.version)
        self.assertEqual(service.detail(self.visitor, self.facility.pk)["areas"], [])
        membership = self.join(self.other)
        role = ClubRoleAssignment.objects.create(membership=membership, role="coach", accepted_at=timezone.now())
        self.assertEqual(len(service.detail(self.other, self.facility.pk)["areas"]), 1)
        memberships.revoke_role(self.admin, self.club.pk, role.pk, membership.version)
        with self.assertRaises(service.Http404):
            service.calendar(self.other, self.area.pk, date(2026, 1, 3))

    def test_same_real_world_venue_does_not_share_ownership(self):
        second = service.save(self.admin, self.private.pk, "facility", {"name": self.facility.name, "address": self.facility.address})
        self.assertNotEqual(second.pk, self.facility.pk)
        with self.assertRaises(service.Http404):
            service.save(self.admin, self.private.pk, "facility", {"name": "Stolen"}, object_id=self.facility.pk, version=self.facility.version)
        with self.assertRaises(service.Http404):
            service.save(self.admin, self.private.pk, "area", {"name": "Cross club"}, parent_id=self.facility.pk)

    def test_stale_forms_and_forbidden_fields_do_not_change_data(self):
        with self.assertRaises(service.FacilityConflict):
            service.save(self.admin, self.club.pk, "facility", {"name": "Stale"}, object_id=self.facility.pk, version=999)
        with self.assertRaises(ValidationError):
            service.save(self.admin, self.club.pk, "facility", {"club_id": self.private.pk}, object_id=self.facility.pk, version=self.facility.version)
        self.facility.refresh_from_db()
        self.assertEqual(self.facility.name, "Synthetic range")

    def test_invalid_coordinates_capacity_timezone_and_distances(self):
        for changes in ({"latitude": 91}, {"longitude": None}, {"timezone": "Unknown/Nowhere"}):
            with self.assertRaises(ValidationError):
                service.save(self.admin, self.club.pk, "facility", changes, object_id=self.facility.pk, version=self.facility.version)
        for changes in ({"lane_capacity": 0}, {"target_capacity": 1001}, {"disciplines": ["wrong"]}, {"distances_m": [-18]}, {"distances_m": [True]}):
            with self.assertRaises(ValidationError):
                service.save(self.admin, self.club.pk, "area", changes, object_id=self.area.pk, version=self.area.version)

    def test_multiple_daily_slots_and_seasonal_priority(self):
        self.rule()
        self.rule(start_time=time(13), end_time=time(16))
        self.rule(starts_on=date(2026, 6, 1), ends_on=date(2026, 8, 31), priority=10, start_time=time(10), end_time=time(14))
        self.assertEqual(len(self.calendar(date(2026, 1, 3))["slots"]), 2)
        summer = self.calendar(date(2026, 6, 6))["slots"]
        self.assertEqual(len(summer), 1)
        self.assertIn("T10:00:00+01:00", summer[0]["start"])
        self.assertIn("T09:00:00+00:00", summer[0]["start_utc"])
        self.assertEqual(len(self.calendar(date(2026, 9, 5))["slots"]), 2)

    def test_overlapping_rules_same_priority_rejected_adjacent_allowed(self):
        self.rule()
        with self.assertRaises(ValidationError):
            self.rule(start_time=time(11), end_time=time(13))
        self.rule(start_time=time(12), end_time=time(13))
        self.assertEqual(len(self.calendar(date(2026, 1, 3))["slots"]), 2)

    def test_hidden_override_cannot_fall_back_to_public_hours_or_disclose_reason(self):
        self.rule()
        self.exception(audience="admins", reason="PRIVATE CLOSURE REASON")
        day = self.calendar(date(2026, 5, 2))
        self.assertEqual(day["slots"], [])
        self.assertNotIn("PRIVATE", str(day))
        self.assertEqual(self.calendar(date(2026, 5, 2), self.admin)["notice"], "PRIVATE CLOSURE REASON")

    def test_replacement_hours_and_exception_priority(self):
        self.rule()
        self.exception()
        self.exception(priority=10, kind="replace", replacement_slots=[{"start": "17:00", "end": "19:00"}, {"start": "20:00", "end": "21:00"}])
        self.assertEqual(len(self.calendar(date(2026, 5, 2))["slots"]), 2)
        with self.assertRaises(ValidationError):
            self.exception(priority=10)

    def test_invalid_replacement_windows_and_date_range(self):
        for changes in ({"kind": "replace", "replacement_slots": [{"start": "12:00", "end": "09:00"}]},
                {"kind": "replace", "replacement_slots": [{"start": "09:00", "end": "12:00"}, {"start": "11:00", "end": "13:00"}]},
                {"ends_on": date(2026, 1, 1)}, {"kind": "closed", "replacement_slots": [{"start": "09:00", "end": "10:00"}]}):
            with self.assertRaises(ValidationError):
                self.exception(**changes)

    def test_dst_gap_and_fold_are_not_advertised_as_confirmed(self):
        self.rule(weekday=6, start_time=time(1, 30), end_time=time(3))
        for day in (date(2026, 3, 29), date(2026, 10, 25)):
            result = self.calendar(day)
            self.assertEqual(result["slots"], [])
            self.assertIn("clock change", result["notice"])
        self.assertEqual(len(self.calendar(date(2026, 3, 22))["slots"]), 1)

    def test_timezone_is_per_facility_not_hardcoded(self):
        service.save(self.admin, self.club.pk, "facility", {"timezone": "America/New_York"}, object_id=self.facility.pk, version=self.facility.version)
        self.rule(start_time=time(9), end_time=time(12))
        self.assertIn("-05:00", self.calendar(date(2026, 1, 3))["slots"][0]["start"])

    def test_archive_preserves_records_and_revokes_saved_urls(self):
        rule = self.rule()
        service.save(self.admin, self.club.pk, "facility", {"active": False}, object_id=self.facility.pk, version=self.facility.version)
        self.assertTrue(ShootingArea.objects.filter(pk=self.area.pk).exists())
        self.assertTrue(type(rule).objects.filter(pk=rule.pk).exists())
        self.assertEqual(self.client.get(reverse("clubs:facility", args=[self.facility.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("clubs:facility-calendar", args=[self.area.pk])).status_code, 404)

    def test_suspended_club_and_lost_admin_denied(self):
        self.club.status = "suspended"
        self.club.save()
        with self.assertRaises(service.Http404):
            service.detail(self.admin, self.facility.pk)
        with self.assertRaises(service.Http404):
            service.save(self.admin, self.club.pk, "facility", {"name": "No"})

    def test_event_provider_receives_scoped_aware_interval_or_reports_unconnected(self):
        self.rule()
        self.assertIsNone(self.calendar(date(2026, 1, 3))["slots"][0]["conflicts"])
        provider = mock.Mock(return_value=["Synthetic permitted event"])
        result = service.calendar(self.visitor, self.area.pk, date(2026, 1, 3), 1, event_provider=provider)
        self.assertEqual(result["days"][0]["slots"][0]["conflicts"], ["Synthetic permitted event"])
        self.assertIsNotNone(provider.call_args.kwargs["starts_at"].tzinfo)

    def test_http_admin_mfa_create_update_calendar_and_cross_club(self):
        url = reverse("clubs:facility-manage", args=[self.club.pk])
        self.client.force_login(self.admin)
        self.assertIn(reverse("mfa_index"), self.client.get(url).url)
        login_with_mfa(self.client, self.admin)
        self.assertContains(self.client.get(url), "Add a facility")
        create = reverse("clubs:facility-new", args=[self.club.pk])
        self.assertEqual(self.client.post(create, {"name": "HTTP venue", "timezone": "Europe/Dublin", "audience": "public", "location_audience": "admins", "active": "on"}).status_code, 302)
        edit = reverse("clubs:facility-edit", args=[self.club.pk, "facility", self.facility.pk])
        data = dict(name="Updated HTTP venue", timezone="Europe/Dublin", audience="public", location_audience="admins", active="on", version=999)
        self.assertEqual(self.client.post(edit, data).status_code, 409)
        self.assertEqual(self.client.get(reverse("clubs:facility-edit", args=[self.private.pk, "facility", self.facility.pk])).status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.rule()
        calendar = self.client.get(reverse("clubs:facility-calendar", args=[self.area.pk]), {"starts_on": "2026-01-03", "days": 7, "format": "json"})
        self.assertEqual(calendar.status_code, 200)
        self.assertFalse(calendar.json()["event_checks_connected"])

    def test_http_area_rule_and_exception_forms(self):
        login_with_mfa(self.client, self.admin)
        area_url = reverse("clubs:facility-add", args=[self.club.pk, "area", self.facility.pk])
        self.assertContains(self.client.get(area_url), "Distances in metres")
        response = self.client.post(area_url, dict(name="Indoor HTTP", kind="indoor", disciplines=["compound"], distances_m="5, 18", lane_capacity=5, target_capacity=3, audience="members", active="on"))
        self.assertEqual(response.status_code, 302)
        rule_url = reverse("clubs:facility-add", args=[self.club.pk, "rule", self.area.pk])
        self.assertEqual(self.client.post(rule_url, dict(weekday=5, starts_on="2026-01-01", start_time="09:00", end_time="12:00", priority=0, audience="public", active="on")).status_code, 302)
        exception_url = reverse("clubs:facility-add", args=[self.club.pk, "exception", self.area.pk])
        self.assertEqual(self.client.post(exception_url, dict(starts_on="2026-05-02", ends_on="2026-05-02", kind="closed", reason="Synthetic closure", priority=0, audience="public", active="on")).status_code, 302)

    def test_csrf_feature_gate_and_invalid_calendar_parameters(self):
        client = Client(enforce_csrf_checks=True)
        login_with_mfa(client, self.admin)
        self.assertEqual(client.post(reverse("clubs:facility-new", args=[self.club.pk]), {}).status_code, 403)
        url = reverse("clubs:facility-calendar", args=[self.area.pk])
        for data in ({"starts_on": "bad", "format": "json"}, {"starts_on": "2026-01-01", "days": 999, "format": "json"}):
            self.assertEqual(self.client.get(url, data).status_code, 400)
        with self.settings(CLUB_FACILITIES_ENABLED=False):
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.get(reverse("clubs:facility", args=[self.facility.pk])).status_code, 404)

    def test_named_groups_are_club_scoped_and_exit_removes_access(self):
        member = self.join()
        group = service.save_group(self.admin, self.club.pk, name="Synthetic evening group", member_ids=[member.pk])
        self.rule(audience="group", access_group=group)
        self.assertEqual(self.calendar(date(2026, 1, 3))["slots"], [])
        self.assertEqual(len(self.calendar(date(2026, 1, 3), self.member)["slots"]), 1)
        private_member = service.ClubMembership.objects.get(club=self.private, user=self.admin)
        with self.assertRaises(ValidationError):
            service.save_group(self.admin, self.club.pk, name="Wrong club", member_ids=[private_member.pk])
        memberships.end_membership(self.member, self.club.pk, member.pk, "left", member.version)
        self.join()
        self.assertEqual(self.calendar(date(2026, 1, 3), self.member)["slots"], [])

    def test_group_location_and_archival_respect_current_group(self):
        member = self.join()
        group = service.save_group(self.admin, self.club.pk, name="Location group", member_ids=[member.pk])
        service.save(self.admin, self.club.pk, "facility", {"location_audience": "group", "location_group": group}, object_id=self.facility.pk, version=self.facility.version)
        self.assertNotIn("address", service.detail(self.visitor, self.facility.pk))
        self.assertEqual(service.detail(self.member, self.facility.pk)["address"], "PRIVATE EXACT ADDRESS")
        service.save_group(self.admin, self.club.pk, name=group.name, member_ids=[member.pk], active=False, group_id=group.pk, version=group.version)
        self.assertNotIn("address", service.detail(self.member, self.facility.pk))

    def test_group_form_and_foreign_group_rejection(self):
        member = self.join()
        login_with_mfa(self.client, self.admin)
        url = reverse("clubs:facility-group-new", args=[self.club.pk])
        self.assertContains(self.client.get(url), "Members")
        self.assertEqual(self.client.post(url, {"name": "HTTP group", "members": [member.pk], "active": "on"}).status_code, 302)
        group = service.save_group(self.admin, self.private.pk, name="Private group", member_ids=[])
        with self.assertRaises(ValidationError):
            self.rule(audience="group", access_group=group)

    def test_public_admin_projection_requires_fresh_mfa(self):
        self.client.force_login(self.admin)
        for url in (reverse("clubs:facility", args=[self.facility.pk]), reverse("clubs:facilities", args=[self.club.pk]),
                reverse("clubs:facility-calendar", args=[self.area.pk])):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("mfa_index"), response.url)

    def test_production_photos_fail_closed_without_private_azure_configuration(self):
        from .checks import facility_photo_readiness
        with self.settings(CLUBS_PRODUCTION=True, CLUB_FACILITY_PHOTO_BACKEND="local"):
            self.assertEqual([error.id for error in facility_photo_readiness(None)], ["clubs.E004"])
        with self.settings(CLUBS_PRODUCTION=True, CLUB_FACILITY_PHOTO_BACKEND="disabled"):
            self.assertEqual(facility_photo_readiness(None), [])


def image_upload():
    output = BytesIO()
    Image.new("RGB", (60, 40), "green").save(output, "PNG")
    return SimpleUploadedFile("synthetic.png", output.getvalue(), content_type="image/png")


@override_settings(CLUBS_ENABLED=True, CLUB_MEMBERSHIPS_ENABLED=True, CLUB_FACILITIES_ENABLED=True)
class FacilityPhotoTests(FacilityFixtures, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.config = override_settings(CLUB_FACILITY_PHOTO_BACKEND="local", CLUB_FACILITY_PHOTO_ROOT=self.folder.name)
        self.config.enable()
        self.addCleanup(self.config.disable)

    def upload(self, **changes):
        self.facility.refresh_from_db()
        data = dict(caption="Synthetic range photo", audience="public", primary=True, version=self.facility.version)
        data.update(changes)
        return service.upload_photo(self.admin, self.club.pk, self.facility.pk, image_upload(), **data)

    def test_multiple_photos_primary_switch_no_metadata_and_controlled_access(self):
        first = self.upload()
        second = self.upload()
        first.refresh_from_db()
        self.assertFalse(first.primary)
        self.assertEqual(first.version, 2)
        self.assertTrue(second.primary)
        response = self.client.get(reverse("clubs:facility-photo", args=[second.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(Image.open(BytesIO(response.content)).format, "JPEG")
        self.assertNotIn("storage_key", str(service.detail(self.visitor, self.facility.pk)))

    def test_private_photo_denied_then_archive_revokes_saved_url(self):
        photo = self.upload(audience="admins")
        url = reverse("clubs:facility-photo", args=[photo.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        login_with_mfa(self.client, self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)
        service.photo_action(self.admin, self.club.pk, photo.pk, "archive", photo.version)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertTrue((Path(self.folder.name)/photo.storage_key).exists())

    def test_storage_failure_and_stale_upload_do_not_leave_untracked_blob(self):
        with mock.patch.object(service.FacilityPhotoStore, "put", side_effect=OSError("synthetic outage")):
            with self.assertRaises(OSError):
                self.upload()
        self.assertEqual(FacilityPhotoUpload.objects.count(), 0)
        with self.assertRaises(service.FacilityConflict):
            self.upload(version=999)
        self.assertEqual(FacilityPhotoUpload.objects.count(), 0)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_orphan_cleanup_retry_preserves_linked_and_archived_photos(self):
        photo = self.upload()
        linked = FacilityPhotoUpload.objects.create(storage_key=photo.storage_key)
        orphan_key = "a"*32+".jpg"
        service.FacilityPhotoStore().put(b"synthetic orphan", key=orphan_key)
        orphan = FacilityPhotoUpload.objects.create(storage_key=orphan_key)
        FacilityPhotoUpload.objects.filter(pk__in=[linked.pk, orphan.pk]).update(created_at=timezone.now()-timedelta(days=2))
        self.assertEqual(service.cleanup_uploads(), 1)
        self.assertTrue((Path(self.folder.name)/orphan_key).exists())
        self.assertEqual(service.cleanup_uploads(apply=True), 1)
        self.assertEqual(service.cleanup_uploads(apply=True), 0)
        self.assertTrue((Path(self.folder.name)/photo.storage_key).exists())

    def test_http_photo_upload_and_cross_facility_action_denied(self):
        login_with_mfa(self.client, self.admin)
        url = reverse("clubs:facility-photos", args=[self.club.pk, self.facility.pk])
        self.assertEqual(self.client.post(url, {"action": "upload", "version": self.facility.version,
            "caption": "Synthetic HTTP photo", "audience": "members", "primary": "on", "upload": image_upload()}).status_code, 302)
        photo = FacilityPhoto.objects.get()
        other = service.save(self.admin, self.club.pk, "facility", {"name": "Other venue"})
        other_url = reverse("clubs:facility-photos", args=[self.club.pk, other.pk])
        self.assertEqual(self.client.post(other_url, {"action": "archive", "photo": photo.pk, "version": photo.version}).status_code, 404)

    def test_invalid_photo_types_and_private_storage_path(self):
        with self.assertRaises(ValidationError):
            service.upload_photo(self.admin, self.club.pk, self.facility.pk,
                SimpleUploadedFile("bad.svg", b"<svg/>", content_type="image/svg+xml"), caption="No", audience="public", primary=True, version=self.facility.version)
        with self.assertRaises(ValidationError):
            service.FacilityPhotoStore().get("../private.jpg")


@skipUnless(connection.vendor == "postgresql", "Requires disposable PostgreSQL row locks")
@override_settings(CLUBS_ENABLED=True, CLUB_MEMBERSHIPS_ENABLED=True, CLUB_FACILITIES_ENABLED=True)
class FacilityConcurrencyTests(FacilityFixtures, TransactionTestCase):
    def test_concurrent_overlapping_rules_cannot_both_be_created(self):
        from django.contrib.auth import get_user_model
        def create(_):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.admin.pk)
                service.save(actor, self.club.pk, "rule", dict(weekday=5, starts_on=date(2026, 1, 1),
                    start_time=time(9), end_time=time(12), priority=0, audience="public"), parent_id=self.area.pk)
                return "created"
            except ValidationError:
                return "blocked"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(create, range(2)))
        self.assertCountEqual(outcomes, ["created", "blocked"])
