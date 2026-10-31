(() => {
  const button = document.getElementById('programme-add-session');
  const total = document.getElementById('id_sessions-TOTAL_FORMS');
  const maximum = document.getElementById('id_sessions-MAX_NUM_FORMS');
  const container = document.getElementById('programme-session-rows');
  const template = document.getElementById('programme-session-empty');
  if (!button || !total || !maximum || !container || !template) return;
  const refresh = () => { button.disabled = Number(total.value) >= Number(maximum.value); };
  button.addEventListener('click', () => {
    const index = Number(total.value);
    if (!Number.isInteger(index) || index >= Number(maximum.value)) return;
    const fragment = template.content.cloneNode(true);
    fragment.querySelectorAll('[name], [id], [for]').forEach(node => {
      for (const attribute of ['name', 'id', 'for']) {
        if (node.hasAttribute(attribute)) node.setAttribute(attribute, node.getAttribute(attribute).replaceAll('__prefix__', String(index)));
      }
    });
    container.appendChild(fragment);
    total.value = String(index + 1);
    refresh();
    container.lastElementChild.querySelector('select, input, textarea')?.focus();
  });
  refresh();
})();
