(() => {
  const entries = JSON.parse(document.getElementById('pending-data').textContent);
  const form = document.getElementById('registration-form');
  const button = document.getElementById('register-button');
  const error = document.getElementById('queue-error');
  const labels = {c: 'Cliente', f: 'Fornecedor', a: 'Cliente e fornecedor'};
  const digits = value => String(value || '').replace(/\D/g, '');
  let submitting = false;
  function validationError(entry) {
    const cnpj = String(entry.cnpj || '').trim();
    if (!/^(?:[0-9]{14}|[0-9]{2}\.[0-9]{3}\.[0-9]{3}\/[0-9]{4}-[0-9]{2})$/.test(cnpj)) {
      return 'Informe um CNPJ válido com 14 dígitos.';
    }
    const number = digits(cnpj);
    if (/^([0-9])\1{13}$/.test(number)) return 'CNPJ inválido.';
    for (let length = 12; length <= 13; length++) {
      let sum = 0;
      for (let index = 0; index < length; index++) {
        sum += Number(number[index]) * (2 + ((length - 1 - index) % 8));
      }
      const remainder = sum % 11;
      if (Number(number[length]) !== (remainder < 2 ? 0 : 11 - remainder)) return 'CNPJ inválido.';
    }
    const ie = String(entry.ie || '').trim();
    if (ie && !/^[0-9]+$/.test(ie) && ie.toLowerCase() !== 'isento') {
      return 'Inscrição estadual inválida. Informe apenas números ou “isento”.';
    }
    if (!Object.hasOwn(labels, entry.type)) return 'Selecione um tipo de cadastro válido.';
    return null;
  }
  function showError(message) {
    error.textContent = message;
    error.hidden = false;
  }
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
    const message = validationError(entry);
    if (message) {
      showError(message);
      return;
    }
    if (entry.ie.toLowerCase() === 'isento') entry.ie = 'isento';
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
    const seen = new Set();
    for (const [index, entry] of entries.entries()) {
      const message = validationError(entry);
      if (message || seen.has(digits(entry.cnpj))) {
        event.preventDefault();
        showError(`Cadastro ${index + 1}: ${message || 'CNPJ duplicado na lista.'}`);
        return;
      }
      seen.add(digits(entry.cnpj));
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
