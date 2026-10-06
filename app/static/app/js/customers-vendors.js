(() => {
  const entries = JSON.parse(document.getElementById('pending-data').textContent);
  const form = document.getElementById('registration-form');
  const button = document.getElementById('register-button');
  const error = document.getElementById('queue-error');
  const labels = {c: 'Cliente', f: 'Fornecedor', a: 'Cliente e fornecedor'};
  const digits = value => String(value || '').replace(/\D/g, '');
  let submitting = false;
  function render() {
    const body = document.getElementById('pending-entries');
    body.replaceChildren();
    entries.forEach((entry, index) => {
      const row = document.createElement('tr');
      [entry.cnpj, entry.ie || 'Não informada', labels[entry.type] || entry.type].forEach(value => {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.appendChild(cell);
      });
      const actions = document.createElement('td');
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'button small';
      remove.textContent = 'Remover';
      remove.setAttribute('aria-label', `Remover CNPJ ${entry.cnpj}`);
      remove.addEventListener('click', () => {
        if (submitting) return;
        entries.splice(index, 1);
        render();
      });
      actions.appendChild(remove);
      row.appendChild(actions);
      body.appendChild(row);
    });
    document.getElementById('pending-count').textContent = entries.length;
    document.getElementById('empty-queue').hidden = entries.length > 0;
    document.getElementById('pending-table').hidden = entries.length === 0;
    document.getElementById('batch-payload').value = JSON.stringify(entries);
    button.disabled = entries.length === 0;
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (submitting) return;
    error.hidden = true;
    const entry = {cnpj: form.elements.cnpj.value.trim(), ie: form.elements.ie.value.trim(), type: form.elements.type.value};
    if (entries.some(item => digits(item.cnpj) === digits(entry.cnpj))) {
      error.textContent = 'Esse CNPJ já está na lista de cadastros.';
      error.hidden = false;
      return;
    }
    entries.push(entry);
    form.elements.cnpj.value = '';
    form.elements.ie.value = '';
    render();
    form.elements.cnpj.focus();
  });
  document.getElementById('batch-form').addEventListener('submit', event => {
    if (submitting || !entries.length) {
      event.preventDefault();
      return;
    }
    if (form.elements.cnpj.value.trim() || form.elements.ie.value.trim()) {
      event.preventDefault();
      error.textContent = 'Adicione o cadastro preenchido à lista ou limpe os campos antes de cadastrar todos.';
      error.hidden = false;
      return;
    }
    submitting = true;
    button.disabled = true;
    document.getElementById('add-button').disabled = true;
    button.textContent = 'Cadastrando…';
  });
  render();
})();
