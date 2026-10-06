document.getElementById('registration-form').addEventListener('submit', () => {
  const button = document.getElementById('register-button');
  button.disabled = true;
  button.textContent = 'Cadastrando…';
});
