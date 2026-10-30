(() => {
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
