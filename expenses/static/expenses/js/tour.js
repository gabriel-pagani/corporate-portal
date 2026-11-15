// O guia passo a passo: cada passo destaca um elemento da tela e explica, num
// balão, o que fazer. Passo com `espera` é a pessoa quem faz: o balão não tem
// botão, só o elemento destacado responde ao toque, e o guia avança sozinho
// quando `espera()` dá verdadeiro. Passo sem `espera` só explica e avança no
// Próximo. Fora do balão e da `area` do passo (por padrão, o próprio elemento
// dos passos com `espera`), nenhum toque passa. Passo sem elemento, ou com ele
// escondido, aparece no centro da tela.
//
//   iniciarTour([
//       { titulo: 'Bem-vindo', texto: '...' },
//       { alvo: '#new-expense', titulo: '...', texto: 'Toque em Nova despesa.', espera: () => !editor.hidden },
//   ], { aoTerminar: () => {} });

const INTERVALO_DO_TOUR = 250;

function iniciarTour(passos, { aoTerminar = () => {} } = {}) {
    const destaque = document.createElement('div');
    destaque.className = 'tour-highlight';
    const balao = document.createElement('div');
    balao.className = 'tour-bubble';
    balao.setAttribute('role', 'dialog');
    balao.setAttribute('aria-labelledby', 'tour-title');
    balao.setAttribute('aria-live', 'polite');
    balao.innerHTML = `
        <p class="tour-step" id="tour-step"></p>
        <h2 id="tour-title"></h2>
        <p class="tour-text" id="tour-text"></p>
        <div class="tour-actions">
            <button type="button" class="tour-button primary" id="tour-next"></button>
        </div>`;
    document.body.append(destaque, balao);
    const proximo = document.getElementById('tour-next');

    let atual = 0;
    // O elemento do passo é rolado para a vista uma vez, quando aparece
    let rolado = false;

    const elementoDo = (passo) => {
        const seletor = typeof passo.alvo === 'function' ? passo.alvo() : passo.alvo;
        const elemento = seletor && document.querySelector(seletor);
        // Sem tamanho na tela é porque está escondido: o passo vai para o centro
        return elemento && elemento.getClientRects().length ? elemento : null;
    };

    const posicionar = () => {
        const elemento = elementoDo(passos[atual]);
        balao.classList.toggle('centered', !elemento);
        destaque.classList.toggle('centered', !elemento);
        if (!elemento) {
            // A posição do passo anterior fica no style do elemento e venceria o CSS do centro
            balao.style.top = balao.style.left = '';
            destaque.removeAttribute('style');
            return;
        }
        if (!rolado) {
            elemento.scrollIntoView({ block: 'center' });
            rolado = true;
        }
        const caixa = elemento.getBoundingClientRect();
        const folga = 6;
        Object.assign(destaque.style, {
            top: `${caixa.top - folga}px`,
            left: `${caixa.left - folga}px`,
            width: `${caixa.width + folga * 2}px`,
            height: `${caixa.height + folga * 2}px`,
        });
        // O balão vai embaixo do elemento; sem espaço, vai em cima
        const margem = 12;
        const alturaDoBalao = balao.offsetHeight;
        const embaixo = caixa.bottom + folga + margem;
        const top = embaixo + alturaDoBalao <= window.innerHeight
            ? embaixo
            : Math.max(margem, caixa.top - folga - margem - alturaDoBalao);
        const left = Math.min(
            Math.max(margem, caixa.left + caixa.width / 2 - balao.offsetWidth / 2),
            window.innerWidth - balao.offsetWidth - margem,
        );
        balao.style.top = `${top}px`;
        balao.style.left = `${left}px`;
    };

    const mostrar = () => {
        const passo = passos[atual];
        rolado = false;
        document.getElementById('tour-step').textContent = `${atual + 1} de ${passos.length}`;
        document.getElementById('tour-title').textContent = passo.titulo;
        document.getElementById('tour-text').textContent = passo.texto;
        proximo.textContent = atual === passos.length - 1 ? 'Entendi' : 'Próximo';
        proximo.hidden = Boolean(passo.espera);
        posicionar();
        if (!passo.espera) proximo.focus();
    };

    const avancar = () => {
        if (atual === passos.length - 1) {
            terminar();
            return;
        }
        atual += 1;
        mostrar();
    };

    // A tela muda com o que a pessoa faz (o editor abre, a lista se redesenha): o destaque
    // acompanha, e o passo dela termina quando a tela chega aonde ele esperava
    const relogio = setInterval(() => {
        if (passos[atual].espera?.()) avancar();
        else posicionar();
    }, INTERVALO_DO_TOUR);

    // Só passa o toque no balão, na área do passo e na janela de confirmação, que o passo pode abrir
    const barrar = (evento) => {
        const passo = passos[atual];
        const area = passo.area ?? (passo.espera ? passo.alvo : null);
        const seletor = typeof area === 'function' ? area() : area;
        const alvo = evento.target;
        if (balao.contains(alvo) || alvo.closest?.('dialog[open]') || (seletor && alvo.closest?.(seletor))) return;
        evento.preventDefault();
        evento.stopPropagation();
    };
    document.addEventListener('click', barrar, true);

    const terminar = () => {
        clearInterval(relogio);
        window.removeEventListener('resize', posicionar);
        document.removeEventListener('click', barrar, true);
        destaque.remove();
        balao.remove();
        aoTerminar();
    };

    proximo.addEventListener('click', avancar);
    window.addEventListener('resize', posicionar);
    mostrar();
}
