// O guia passo a passo: cada passo destaca um elemento da tela e explica, num
// balão, o que ele faz. A pessoa só toca em Próximo: a `acao` do passo, se
// houver, roda nesse toque e mostra na tela o que aconteceria (o editor abre, a
// despesa vai para a lista). O resto da página fica inerte enquanto o guia está
// aberto. Passo sem elemento, ou com ele escondido, aparece no centro da tela.
//
//   iniciarTour([{ alvo: '#new-expense', titulo: '...', texto: '...', acao: () => abrirFotos() }], {
//       bloquear: document.getElementById('content'), aoTerminar: () => {},
//   });

const INTERVALO_DO_TOUR = 250;

function iniciarTour(passos, { bloquear = null, aoTerminar = () => {} } = {}) {
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
    // Só o balão responde: a página não recebe toque nem foco até o guia acabar
    if (bloquear) bloquear.inert = true;

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
        posicionar();
        proximo.focus();
    };

    // A tela muda com as ações do guia (o editor abre, a lista se redesenha): o destaque acompanha
    const relogio = setInterval(posicionar, INTERVALO_DO_TOUR);

    const terminar = () => {
        clearInterval(relogio);
        window.removeEventListener('resize', posicionar);
        destaque.remove();
        balao.remove();
        if (bloquear) bloquear.inert = false;
        aoTerminar();
    };

    proximo.addEventListener('click', async () => {
        if (proximo.disabled) return;
        proximo.disabled = true;
        try {
            await passos[atual].acao?.();
        } finally {
            proximo.disabled = false;
        }
        if (atual === passos.length - 1) {
            terminar();
            return;
        }
        atual += 1;
        mostrar();
    });
    window.addEventListener('resize', posicionar);
    mostrar();
}
