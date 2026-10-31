(() => {
  if (document.querySelector('[data-equipment-section="overview"]') && location.hash) {
    const key = location.hash.slice(1);
    const link = [...document.querySelectorAll('[data-equipment-link]')].find(a => a.dataset.equipmentLink === key);
    if (link) location.replace(link.href);
  }
  const category = document.getElementById('id_category');
  if (!category) return;
  function refresh() {
    document.querySelectorAll('[data-component-category]').forEach(row => {
      const visible = !row.dataset.componentCategory || row.dataset.componentCategory === category.value;
      row.hidden = !visible;
      row.querySelectorAll('input,select,textarea').forEach(input => { input.disabled = !visible; });
    });
  }
  category.addEventListener('change', refresh);
  refresh();
})();
