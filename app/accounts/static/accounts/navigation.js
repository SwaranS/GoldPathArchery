// Warn before leaving a changed form; normal form submission remains unaffected.
let changed = false;
document.addEventListener('input', event => {
  if (event.target.closest('form')) changed = true;
});
document.addEventListener('submit', () => { changed = false; });
window.addEventListener('beforeunload', event => {
  if (changed) { event.preventDefault(); event.returnValue = ''; }
});
