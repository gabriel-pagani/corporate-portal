// A configuração da tela vem em data-attributes: com o CSP ligado, o navegador
// recusa <script> inline, que é onde essas constantes morariam.
const {
    csrfToken: CSRF_TOKEN,
    competenciesUrl: COMPETENCIAS_API_URL,
    competencyUrl: COMPETENCIA_API_URL,
    finishUrl: FINALIZAR_API_URL,
    bankHoursNotesUrl: OBSERVACOES_DO_BANCO_API_URL,
    indicatorsUrl: INDICADORES_API_URL,
    competencyIndicatorsUrl: INDICADORES_DA_COMPETENCIA_API_URL,
    reportsUrl: RELATORIOS_API_URL,
    treatmentsUrl: TRATATIVAS_API_URL,
    recurrenceUrl: RECORRENCIA_API_URL,
} = document.getElementById('content').dataset;

const ITENS_POR_PAGINA = 50;
const LIMITE_PRIORITARIOS = 8;
const NIVEIS_DE_CALOR = 6;
const ABAS = [
    'visao-geral', 'ocorrencias', 'intervalos', 'banco-de-horas', 'horas-extras', 'ranking-intrajornada',
    'ranking-interjornada', 'graficos', 'recorrencia', 'competencias',
];
const BANCO_DE_HORAS = 'B';

// Os códigos que a tela trata de forma especial; os rótulos vêm do catálogo
const BATIDAS_IMPARES = 'I';
const FALTA = 'F';
const SEM_MARCACOES = 'M';
const INTERVALO_CURTO = 'J';
const INTERJORNADA = 'N';
const HORAS_EXTRAS = 'E';
const HORAS_EXTRAS_ACIMA_DE_2H = 'H';
const TIPOS_DE_INTERVALO = [INTERVALO_CURTO, INTERJORNADA, SEM_MARCACOES];
const TRATATIVAS_DESFAVORAVEIS = ['F', 'S'];
const NAO_PROCEDE = 'N';

const CONFERENCIA = {
    [INTERVALO_CURTO]: 'Calculado pelas batidas',
    [INTERJORNADA]: 'Informação do relatório de interjornada',
    [HORAS_EXTRAS]: 'Informação do sumarizado',
    [HORAS_EXTRAS_ACIMA_DE_2H]: 'Informação do sumarizado',
    [SEM_MARCACOES]: 'Dados insuficientes',
};

const PLACEHOLDERS = {
    [BATIDAS_IMPARES]: 'Descreva o ajuste mensal realizado, o esquecimento confirmado ou a justificativa.',
    [FALTA]: 'Informe a confirmação, o tipo de justificativa ou a suspensão e o período.',
    [SEM_MARCACOES]: 'Informe a conferência e o eventual lançamento do intervalo.',
};

let catalogo = { types: [], treatments: {}, reports: {} };
let tipos = {};
let permissoes = {};
let responsavelPadrao = '';
let competencias = [];
let competencia = null;
let periodo = { start_date: '', end_date: '' };
let ocorrencias = [];
let recorrencia = null;
let ocorrenciaAberta = null;
let enviando = false;
let temporizadorPeriodo = null;
const paginas = { ocorrencias: 1, intervalos: 1, banco: 1, extras: 1, intra: 1, inter: 1, recorrencia: 1 };

// Os rankings vêm do servidor, que soma as competências; a localização, a busca
// e a ordem são aplicadas aqui. O pedido descarta a resposta que chega atrasada.
const RANKINGS = {
    intra: { tipo: INTERVALO_CURTO, linhas: null, pedido: 0 },
    inter: { tipo: INTERJORNADA, linhas: null, pedido: 0 },
};

function escaparHtml(texto) {
    return String(texto ?? '').replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

// Remove acentos e caixa para tornar a pesquisa mais tolerante
function normalizar(texto) {
    return String(texto ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').trim().toLowerCase();
}

function lerJson(id) {
    return JSON.parse(document.getElementById(id).textContent);
}

function urlCom(modelo, id) {
    return modelo.replace('/0/', `/${id}/`);
}

function urlDeIndicadores(escopo) {
    return escopo === 'all' ? INDICADORES_API_URL : urlCom(INDICADORES_DA_COMPETENCIA_API_URL, escopo);
}

function numero(valor) {
    return Number(valor || 0).toLocaleString('pt-BR');
}

function dataBr(iso) {
    if (!iso) return '';
    const [ano, mes, dia] = iso.slice(0, 10).split('-');
    return `${dia}/${mes}/${ano}`;
}

function dataHoraBr(iso) {
    return iso ? new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '';
}

function rotuloPeriodo(inicio, fim) {
    return `${dataBr(inicio)} a ${dataBr(fim)}`;
}

// Minutos em HH:MM, como os relatórios do Ahgora escrevem as horas
function formatarHoras(minutos) {
    const total = Math.abs(minutos || 0);
    return `${minutos < 0 ? '-' : ''}${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

function comparar(a, b) {
    return a.localeCompare(b, 'pt-BR');
}

async function requisitar(url, metodo = 'GET', corpo = null) {
    const opcoes = {
        method: metodo,
        headers: { 'X-CSRFToken': CSRF_TOKEN, 'Accept': 'application/json' },
    };
    if (corpo instanceof FormData) {
        opcoes.body = corpo;
    } else if (corpo !== null) {
        opcoes.headers['Content-Type'] = 'application/json';
        opcoes.body = JSON.stringify(corpo);
    }

    let resposta;
    try {
        resposta = await fetch(url, opcoes);
    } catch (erro) {
        throw new Error('Não foi possível se comunicar com o servidor.');
    }

    // O nginx recusa o arquivo grande antes de ele chegar ao portal, e responde com HTML
    if (resposta.status === 413) {
        throw new Error('O arquivo passa do limite de 20 MB para importação.');
    }
    const dados = await resposta.json().catch(() => ({}));
    if (!resposta.ok) {
        throw new Error(dados.detail || `Erro inesperado (${resposta.status}).`);
    }
    return dados;
}

function mostrarErro(mensagem) {
    document.getElementById('alert-error-text').textContent = mensagem;
    document.getElementById('alert-error').hidden = !mensagem;
}

function mostrarSucesso(mensagem) {
    const aviso = document.getElementById('success-message');
    aviso.textContent = mensagem;
    aviso.hidden = !mensagem;
}

// Uma ação por vez: trocar de competência no meio de um envio misturaria as telas
async function executar(acao) {
    if (enviando) return;
    enviando = true;
    try {
        mostrarErro('');
        await acao();
    } catch (erro) {
        mostrarErro(erro.message);
    } finally {
        enviando = false;
    }
}

function tipo(codigo) {
    return tipos[codigo] || { code: codigo, label: codigo, priority: 'Baixa', actionable: false, treatments: [], serie: 8 };
}

function pendente(ocorrencia) {
    return tipo(ocorrencia.type).actionable && !ocorrencia.treatment;
}

function concluida(ocorrencia) {
    return tipo(ocorrencia.type).actionable && Boolean(ocorrencia.treatment);
}

function textoTratativa(ocorrencia) {
    return ocorrencia.treatment ? catalogo.treatments[ocorrencia.treatment] : tipo(ocorrencia.type).pending_label;
}

function badgePrioridade(prioridade) {
    const classe = { Alta: 'high', 'Média': 'medium', Baixa: 'neutral' }[prioridade] || 'neutral';
    return `<span class="badge ${classe}">${escaparHtml(prioridade)}</span>`;
}

function badgeTratativa(ocorrencia) {
    if (!tipo(ocorrencia.type).actionable) return '<span class="muted">— Informativo</span>';

    let classe = 'done';
    if (!ocorrencia.treatment) classe = 'pending';
    else if (ocorrencia.treatment === NAO_PROCEDE) classe = 'neutral';
    else if (TRATATIVAS_DESFAVORAVEIS.includes(ocorrencia.treatment)) classe = 'high';
    return `<span class="badge ${classe}">${escaparHtml(textoTratativa(ocorrencia))}</span>`;
}

function botaoAbrir(ocorrencia, rotulo) {
    if (!tipo(ocorrencia.type).actionable) return '<span class="muted">—</span>';
    return `<button type="button" class="button small" data-occurrence="${ocorrencia.id}">${rotulo || (permissoes.change ? 'Tratar' : 'Ver')}</button>`;
}

function celulaColaborador(ocorrencia) {
    return `<strong>${escaparHtml(ocorrencia.employee_name)}</strong><div class="muted">${escaparHtml(ocorrencia.location)}</div>`;
}

function contar(lista, condicao) {
    return lista.reduce((total, item) => total + (condicao(item) ? 1 : 0), 0);
}

function opcoesDeLocalizacao(lista) {
    return [...new Set(lista.map((item) => item.location))].sort(comparar).map((nome) => [nome, nome]);
}

// As listas chegam do servidor por data, colaborador e tipo; a ordenação é
// estável, e esse continua sendo o desempate
const ORDENACOES = {
    date: (a, b) => a.day.localeCompare(b.day),
    name: (a, b) => comparar(a.employee_name, b.employee_name),
    location: (a, b) => comparar(a.location, b.location),
    largest: (a, b) => (b.minutes || 0) - (a.minutes || 0),
    smallest: (a, b) => (a.minutes || 0) - (b.minutes || 0),
};

function ordenar(lista, ordem) {
    return [...lista].sort(ORDENACOES[ordem]);
}

// Competência

function definirCompetencia(dados) {
    competencia = dados;
    ocorrencias = dados ? dados.occurrences : [];
    if (dados) {
        periodo = { start_date: dados.competency.start_date, end_date: dados.competency.end_date };
    }
    Object.keys(paginas).forEach((chave) => { paginas[chave] = 1; });
    renderizarTudo();
}

async function abrirCompetencia(id) {
    definirCompetencia(await requisitar(urlCom(COMPETENCIA_API_URL, id)));
}

async function abrirPeriodo() {
    const inicio = document.getElementById('start-date').value;
    const fim = document.getElementById('end-date').value;
    if (!inicio || !fim) throw new Error('Informe o início e o fim da competência.');
    if (fim < inicio) throw new Error('O fim da competência deve ser igual ou posterior ao início.');
    if (competencia && inicio === periodo.start_date && fim === periodo.end_date) return;

    const salva = competencias.find((item) => item.start_date === inicio && item.end_date === fim);
    if (salva) {
        await abrirCompetencia(salva.id);
        return;
    }
    // Período sem nada salvo: a competência nasce com o primeiro relatório importado
    periodo = { start_date: inicio, end_date: fim };
    definirCompetencia(null);
}

async function atualizarCompetencias() {
    competencias = (await requisitar(COMPETENCIAS_API_URL)).competencies;
    renderizarSeletorDeCompetencia();
    renderizarCompetencias();
}

function renderizarSeletorDeCompetencia() {
    const select = document.getElementById('competency-select');
    const atual = competencia ? competencia.competency.id : null;
    select.innerHTML = [
        `<option value="">${competencias.length ? 'Selecione uma competência salva' : 'Nenhuma competência salva'}</option>`,
        ...competencias.map((item) => `
            <option value="${item.id}"${item.id === atual ? ' selected' : ''}>
                ${escaparHtml(rotuloPeriodo(item.start_date, item.end_date))}${item.finished_at ? ' · conferência finalizada' : ''}
            </option>`),
    ].join('');

    document.getElementById('start-date').value = periodo.start_date;
    document.getElementById('end-date').value = periodo.end_date;

    const situacao = document.getElementById('competency-status');
    situacao.textContent = competencia
        ? ''
        : `Nenhum relatório salvo para ${rotuloPeriodo(periodo.start_date, periodo.end_date)}. Importe os relatórios para começar.`;
    situacao.hidden = Boolean(competencia);
    preencherSeletoresDeCompetencia();
}

function preencherSeletoresDeCompetencia() {
    const salvas = competencias.map((item) => [String(item.id), rotuloPeriodo(item.start_date, item.end_date)]);
    Object.keys(RANKINGS).forEach((chave) => {
        preencherOpcoes(
            document.getElementById(`${chave}-scope`),
            [['current', 'Competência aberta'], ['all', 'Todas as competências · total'], ...salvas],
            'current',
        );
    });
}

// Relatórios

function renderizarRelatorios() {
    const relatorios = competencia ? competencia.reports : {};
    document.querySelectorAll('[data-report-state]').forEach((estado) => {
        const codigo = estado.dataset.reportState;
        const relatorio = relatorios[codigo];
        estado.classList.remove('error');
        estado.classList.toggle('loaded', Boolean(relatorio));
        estado.textContent = relatorio
            ? `✓ ${relatorio.file_name} · ${numero(relatorio.row_count)} ${codigo === BANCO_DE_HORAS ? 'colaboradores' : 'linhas'} · `
              + `enviado por ${relatorio.uploaded_by || 'usuário removido'} em ${dataHoraBr(relatorio.uploaded_at)}`
            : 'Nenhum relatório importado';
    });

    const semSumarizado = competencia && !relatorios.S;
    document.getElementById('reports-hint').classList.toggle('attention', Boolean(semSumarizado));
}

async function importarRelatorio(campo) {
    const arquivo = campo.files[0];
    if (!arquivo) return;
    if (enviando) {
        campo.value = '';
        return;
    }

    const tipoRelatorio = campo.dataset.reportInput;
    const estado = document.querySelector(`[data-report-state="${tipoRelatorio}"]`);
    const campos = document.querySelectorAll('[data-report-input]');
    const corpo = new FormData();
    corpo.append('start_date', periodo.start_date);
    corpo.append('end_date', periodo.end_date);
    corpo.append('type', tipoRelatorio);
    corpo.append('file', arquivo);

    enviando = true;
    campos.forEach((item) => { item.disabled = true; });
    mostrarErro('');
    mostrarSucesso('');
    estado.classList.remove('loaded', 'error');
    estado.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Importando e analisando...';
    try {
        const dados = await requisitar(RELATORIOS_API_URL, 'POST', corpo);
        recorrencia = null;
        definirCompetencia(dados);
        const linhas = numero(dados.reports[tipoRelatorio].row_count);
        mostrarSucesso(tipoRelatorio === BANCO_DE_HORAS
            ? `Banco de horas importado: ${linhas} colaboradores com saldo.`
            : `Relatório "${catalogo.reports[tipoRelatorio]}" importado: ${linhas} linhas. `
              + `${numero(dados.occurrences.length)} ocorrências na competência.`);
        atualizarCompetencias().catch((erro) => mostrarErro(erro.message));
    } catch (erro) {
        renderizarRelatorios();
        // O erro fica junto ao campo do relatório, para ficar claro qual arquivo recusou
        estado.classList.remove('loaded');
        estado.classList.add('error');
        estado.textContent = `Erro: ${erro.message}`;
    } finally {
        enviando = false;
        campos.forEach((item) => { item.disabled = false; });
        campo.value = '';
    }
}

// Indicadores e visão geral

function renderizarIndicadores() {
    const acionaveis = ocorrencias.filter((ocorrencia) => tipo(ocorrencia.type).actionable);
    const pendentes = contar(acionaveis, pendente);
    const concluidas = acionaveis.length - pendentes;
    const porcentagem = acionaveis.length ? Math.round(concluidas / acionaveis.length * 100) : 0;
    const valores = {
        'kpi-pending': pendentes,
        'kpi-absences': contar(ocorrencias, (o) => o.type === FALTA && pendente(o)),
        'kpi-missing-break': contar(ocorrencias, (o) => o.type === SEM_MARCACOES),
        'kpi-done': concluidas,
        'kpi-rows': competencia ? competencia.analysed_rows : 0,
        'kpi-total': ocorrencias.length,
        'kpi-odd-punches': contar(ocorrencias, (o) => o.type === BATIDAS_IMPARES),
        'kpi-short-break': contar(ocorrencias, (o) => o.type === INTERVALO_CURTO),
        'kpi-short-rest': contar(ocorrencias, (o) => o.type === INTERJORNADA),
        'kpi-long-overtime': contar(ocorrencias, (o) => o.type === HORAS_EXTRAS_ACIMA_DE_2H),
    };
    Object.entries(valores).forEach(([id, valor]) => {
        document.getElementById(id).textContent = numero(valor);
    });

    const medidor = document.getElementById('review-meter');
    medidor.setAttribute('aria-valuenow', porcentagem);
    medidor.querySelector('span').style.width = `${porcentagem}%`;
    document.getElementById('review-count').textContent = acionaveis.length
        ? `${numero(concluidas)} de ${numero(acionaveis.length)} tratativas obrigatórias concluídas (${porcentagem}%).`
        : 'Nenhuma tratativa obrigatória nesta competência.';

    const finalizada = competencia && competencia.competency.finished_at;
    const aviso = document.getElementById('review-finished');
    aviso.hidden = !finalizada;
    if (finalizada) {
        const quem = competencia.competency.finished_by;
        aviso.innerHTML = `<i class="fas fa-circle-check"></i> Conferência finalizada em ${escaparHtml(dataHoraBr(finalizada))}`
            + (quem ? ` por ${escaparHtml(quem)}.` : '.');
    }

    const botaoFinalizar = document.getElementById('finish-review');
    if (botaoFinalizar) botaoFinalizar.disabled = !competencia || !ocorrencias.length;
}

function renderizarPrioritarios() {
    const prioridade = { Alta: 0, 'Média': 1, Baixa: 2 };
    const casos = ocorrencias
        .filter(pendente)
        .sort((a, b) => prioridade[tipo(a.type).priority] - prioridade[tipo(b.type).priority] || a.day.localeCompare(b.day))
        .slice(0, LIMITE_PRIORITARIOS);

    document.querySelector('#priority-table tbody').innerHTML = casos.map((ocorrencia) => `
        <tr>
            <td>${dataBr(ocorrencia.day)}</td>
            <td>${escaparHtml(ocorrencia.employee_name)}</td>
            <td>${escaparHtml(ocorrencia.employee_id)}</td>
            <td>${escaparHtml(tipo(ocorrencia.type).label)}</td>
            <td>${badgeTratativa(ocorrencia)}</td>
            <td>${botaoAbrir(ocorrencia, 'Abrir ocorrência')}</td>
        </tr>`).join('');

    const vazio = document.getElementById('priority-empty');
    vazio.hidden = casos.length > 0;
    vazio.textContent = ocorrencias.length ? 'Nenhuma tratativa pendente.' : 'Importe os relatórios para ver os casos prioritários.';
    document.getElementById('priority-table').hidden = casos.length === 0;
}

// Tabelas paginadas

function criarBotaoPagina(rotulo, pagina, aoMudar, ativo = false) {
    const botao = document.createElement('button');
    botao.type = 'button';
    botao.textContent = rotulo;
    botao.classList.add('pagination-button');
    if (ativo) {
        botao.classList.add('active');
        botao.setAttribute('aria-current', 'page');
    }
    botao.addEventListener('click', () => aoMudar(pagina));
    return botao;
}

function criarReticencias() {
    const reticencias = document.createElement('span');
    reticencias.textContent = '...';
    reticencias.classList.add('pagination-ellipsis');
    return reticencias;
}

function renderizarPaginacao(container, totalPaginas, paginaAtual, aoMudar) {
    container.innerHTML = '';
    if (totalPaginas <= 1) return;

    const isMobile = window.innerWidth <= 480;
    const maxVisiveis = isMobile ? 3 : 7;
    let inicio = Math.max(1, paginaAtual - Math.floor(maxVisiveis / 2));
    const fim = Math.min(totalPaginas, inicio + maxVisiveis - 1);
    inicio = Math.max(1, fim - maxVisiveis + 1);

    if (paginaAtual > 1) {
        container.appendChild(criarBotaoPagina(isMobile ? '‹' : '‹ Anterior', paginaAtual - 1, aoMudar));
    }
    if (inicio > 1) {
        container.appendChild(criarBotaoPagina('1', 1, aoMudar));
        if (inicio > 2) container.appendChild(criarReticencias());
    }
    for (let pagina = inicio; pagina <= fim; pagina++) {
        container.appendChild(criarBotaoPagina(pagina, pagina, aoMudar, pagina === paginaAtual));
    }
    if (fim < totalPaginas) {
        if (fim < totalPaginas - 1) container.appendChild(criarReticencias());
        container.appendChild(criarBotaoPagina(totalPaginas, totalPaginas, aoMudar));
    }
    if (paginaAtual < totalPaginas) {
        container.appendChild(criarBotaoPagina(isMobile ? '›' : 'Próximo ›', paginaAtual + 1, aoMudar));
    }
}

function renderizarTabela({ id, chave, linhas, montarLinha, mensagemVazia, renderizar }) {
    const totalPaginas = Math.ceil(linhas.length / ITENS_POR_PAGINA);
    paginas[chave] = Math.min(paginas[chave], Math.max(1, totalPaginas));
    const inicio = (paginas[chave] - 1) * ITENS_POR_PAGINA;

    document.querySelector(`#${id}-table tbody`).innerHTML = linhas.slice(inicio, inicio + ITENS_POR_PAGINA).map(montarLinha).join('');
    document.getElementById(`${id}-table`).hidden = linhas.length === 0;

    const vazio = document.getElementById(`${id}-empty`);
    vazio.hidden = linhas.length > 0;
    vazio.textContent = mensagemVazia;

    renderizarPaginacao(document.getElementById(`${id}-pagination`), totalPaginas, paginas[chave], (pagina) => {
        paginas[chave] = pagina;
        renderizar();
        document.getElementById(`${id}-table`).scrollIntoView({ block: 'start', behavior: 'smooth' });
    });
}

function mensagemSemDados(mensagem) {
    return competencia ? mensagem : 'Importe os relatórios para iniciar a conferência.';
}

// Ocorrências

function preencherOpcoes(select, opcoes, padrao) {
    const atual = select.value;
    select.innerHTML = opcoes.map(([valor, rotulo]) => `<option value="${escaparHtml(valor)}">${escaparHtml(rotulo)}</option>`).join('');
    select.value = opcoes.some(([valor]) => valor === atual) ? atual : padrao;
}

function preencherSelect(id, rotuloTodos, opcoes) {
    preencherOpcoes(document.getElementById(id), [['', rotuloTodos], ...opcoes], '');
}

function atualizarFiltros() {
    const colaboradores = new Map(ocorrencias.map((o) => [o.employee_id, o.employee_name]));
    preencherSelect(
        'filter-employee',
        'Todos os colaboradores',
        [...colaboradores.entries()]
            .sort((a, b) => a[1].localeCompare(b[1], 'pt-BR'))
            .map(([id, nome]) => [id, `${nome} · ${id}`]),
    );
    preencherSelect('filter-location', 'Todas as localizações', opcoesDeLocalizacao(ocorrencias));
    preencherSelect('overtime-location', 'Todas as localizações', opcoesDeLocalizacao(horasExtras()));
    preencherSelect('bank-location', 'Todas as localizações', opcoesDeLocalizacao(saldosDoBanco()));
}

// Os filtros que não dependem dos dados da competência
function montarFiltrosFixos() {
    preencherSelect('filter-type', 'Todos os tipos', catalogo.types.map((item) => [item.code, item.label]));
    preencherSelect('filter-treatment', 'Todas as tratativas', [
        ['pendentes', 'Pendentes'],
        ['concluidas', 'Concluídas'],
        ...Object.entries(catalogo.treatments),
    ]);
    preencherSelect('interval-kind', 'Todos os alertas de intervalo', TIPOS_DE_INTERVALO.map((codigo) => [codigo, tipo(codigo).label]));
    preencherSelect('overtime-kind', 'Todas as horas extras', [HORAS_EXTRAS_ACIMA_DE_2H, HORAS_EXTRAS].map((codigo) => [codigo, tipo(codigo).label]));
}

function ocorrenciasFiltradas() {
    const busca = normalizar(document.getElementById('occurrence-search').value);
    const colaborador = document.getElementById('filter-employee').value;
    const tipoFiltro = document.getElementById('filter-type').value;
    const localizacao = document.getElementById('filter-location').value;
    const prioridade = document.getElementById('filter-priority').value;
    const tratativa = document.getElementById('filter-treatment').value;

    return ocorrencias.filter((ocorrencia) => {
        if (colaborador && ocorrencia.employee_id !== colaborador) return false;
        if (tipoFiltro && ocorrencia.type !== tipoFiltro) return false;
        if (localizacao && ocorrencia.location !== localizacao) return false;
        if (prioridade && tipo(ocorrencia.type).priority !== prioridade) return false;
        if (tratativa === 'pendentes' && !pendente(ocorrencia)) return false;
        if (tratativa === 'concluidas' && !concluida(ocorrencia)) return false;
        if (tratativa && !['pendentes', 'concluidas'].includes(tratativa)
            && (!tipo(ocorrencia.type).actionable || ocorrencia.treatment !== tratativa)) return false;
        if (busca) {
            const texto = [ocorrencia.employee_id, ocorrencia.employee_name, tipo(ocorrencia.type).label, ocorrencia.evidence];
            if (!normalizar(texto.join(' ')).includes(busca)) return false;
        }
        return true;
    });
}

function linhaOcorrencia(ocorrencia) {
    const tipoOcorrencia = tipo(ocorrencia.type);
    return `
        <tr>
            <td>${dataBr(ocorrencia.day)}</td>
            <td class="person">${celulaColaborador(ocorrencia)}</td>
            <td>${escaparHtml(ocorrencia.employee_id)}</td>
            <td>${escaparHtml(tipoOcorrencia.label)}</td>
            <td class="evidence">${escaparHtml(ocorrencia.evidence)}</td>
            <td>${escaparHtml(CONFERENCIA[ocorrencia.type] || 'Conferência necessária')}</td>
            <td>${badgePrioridade(tipoOcorrencia.priority)}</td>
            <td>${badgeTratativa(ocorrencia)}</td>
            <td>${botaoAbrir(ocorrencia)}</td>
        </tr>`;
}

function renderizarOcorrencias() {
    const lista = ocorrenciasFiltradas();
    renderizarTabela({
        id: 'occurrences',
        chave: 'ocorrencias',
        linhas: lista,
        montarLinha: linhaOcorrencia,
        mensagemVazia: mensagemSemDados('Nenhuma ocorrência para os filtros selecionados.'),
        renderizar: renderizarOcorrencias,
    });
    document.getElementById('occurrences-status').textContent = ocorrencias.length
        ? `Mostrando ${numero(lista.length)} de ${numero(ocorrencias.length)} ocorrências.`
        : '';
    document.getElementById('export-excel').disabled = lista.length === 0;
}

function limparFiltros() {
    ['occurrence-search', 'filter-employee', 'filter-type', 'filter-location', 'filter-priority', 'filter-treatment']
        .forEach((id) => { document.getElementById(id).value = ''; });
    paginas.ocorrencias = 1;
}

function irParaOcorrencias({ tipoOcorrencia = '', tratativa = '', localizacao = '' } = {}) {
    limparFiltros();
    document.getElementById('filter-type').value = tipoOcorrencia;
    document.getElementById('filter-treatment').value = tratativa;
    document.getElementById('filter-location').value = localizacao;
    renderizarOcorrencias();
    trocarAba('ocorrencias');
}

// Intervalos e horas extras

function filtrarPorBusca(lista, idBusca, idTipo) {
    const busca = normalizar(document.getElementById(idBusca).value);
    const tipoFiltro = document.getElementById(idTipo).value;
    return lista.filter((ocorrencia) => (!tipoFiltro || ocorrencia.type === tipoFiltro)
        && (!busca || normalizar(`${ocorrencia.employee_name} ${ocorrencia.employee_id}`).includes(busca)));
}

// "Menor intervalo" vem pelos minutos que faltaram, e o dia sem marcações
// suficientes, que não tem intervalo calculado, fica no fim
function ordenarIntervalos(lista, ordem) {
    if (ordem === 'shortest') return [...lista].sort((a, b) => (b.minutes ?? -1) - (a.minutes ?? -1));
    if (ordem !== 'count') return ordenar(lista, ordem);

    const porColaborador = {};
    lista.forEach((ocorrencia) => { porColaborador[ocorrencia.employee_id] = (porColaborador[ocorrencia.employee_id] || 0) + 1; });
    return [...lista].sort((a, b) => porColaborador[b.employee_id] - porColaborador[a.employee_id]
        || comparar(a.employee_name, b.employee_name) || a.employee_id.localeCompare(b.employee_id));
}

function renderizarIntervalos() {
    const lista = ordenarIntervalos(
        filtrarPorBusca(ocorrencias.filter((o) => TIPOS_DE_INTERVALO.includes(o.type)), 'interval-search', 'interval-kind'),
        document.getElementById('interval-sort').value,
    );
    renderizarTabela({
        id: 'intervals',
        chave: 'intervalos',
        linhas: lista,
        montarLinha: (ocorrencia) => `
            <tr>
                <td>${dataBr(ocorrencia.day)}</td>
                <td class="person">${celulaColaborador(ocorrencia)}</td>
                <td>${escaparHtml(ocorrencia.employee_id)}</td>
                <td>${escaparHtml(tipo(ocorrencia.type).label)}</td>
                <td class="evidence">${escaparHtml(ocorrencia.evidence)}</td>
                <td>${ocorrencia.type === SEM_MARCACOES ? 'Conferência necessária' : CONFERENCIA[ocorrencia.type]}</td>
            </tr>`,
        mensagemVazia: mensagemSemDados('Nenhum alerta de intervalo para os filtros selecionados.'),
        renderizar: renderizarIntervalos,
    });
}

// Banco de horas

function saldosDoBanco() {
    return competencia ? competencia.bank_hours : [];
}

const ORDENACOES_DO_BANCO = {
    negative: (a, b) => a.balance - b.balance,
    positive: (a, b) => b.balance - a.balance,
    location: ORDENACOES.location,
    name: ORDENACOES.name,
};

function saldosDaLocalizacao() {
    const localizacao = document.getElementById('bank-location').value;
    return saldosDoBanco().filter((saldo) => !localizacao || saldo.location === localizacao);
}

function saldosFiltrados() {
    const busca = normalizar(document.getElementById('bank-search').value);
    return saldosDaLocalizacao()
        .filter((saldo) => !busca || normalizar(`${saldo.employee_name} ${saldo.employee_id}`).includes(busca))
        .sort(ORDENACOES_DO_BANCO[document.getElementById('bank-sort').value]);
}

function autoriaDaObservacao(saldo) {
    return saldo.note_at ? `Salva por ${saldo.note_by || 'usuário removido'} em ${dataHoraBr(saldo.note_at)}` : '';
}

function linhaDoBanco(saldo) {
    const observacao = permissoes.change
        ? `<textarea class="bank-note" data-bank-note="${escaparHtml(saldo.employee_id)}" rows="2"
               aria-label="${escaparHtml(`Observações para ${saldo.employee_name}`)}"
               placeholder="Justificativa solicitada, retorno do supervisor...">${escaparHtml(saldo.note)}</textarea>`
        : `<span class="note-text">${escaparHtml(saldo.note || '—')}</span>`;
    return `
        <tr>
            <td class="person"><strong>${escaparHtml(saldo.employee_name)}</strong></td>
            <td>${escaparHtml(saldo.employee_id)}</td>
            <td>${escaparHtml(saldo.location)}</td>
            <td><span class="badge ${saldo.balance < 0 ? 'high' : 'neutral'}">${formatarHoras(saldo.balance)}</span></td>
            <td class="bank-note-cell">${observacao}<div class="note-author">${escaparHtml(autoriaDaObservacao(saldo))}</div></td>
        </tr>`;
}

function renderizarBancoDeHoras() {
    // Os totais seguem só a localização; a busca filtra a tabela
    const saldos = saldosDaLocalizacao();
    const somar = (lista) => lista.reduce((total, saldo) => total + saldo.balance, 0);
    document.getElementById('bank-net').textContent = formatarHoras(somar(saldos));
    document.getElementById('bank-positive').textContent = formatarHoras(somar(saldos.filter((saldo) => saldo.balance > 0)));
    document.getElementById('bank-negative').textContent = formatarHoras(somar(saldos.filter((saldo) => saldo.balance < 0)));
    document.getElementById('bank-people').textContent = numero(saldos.length);

    const lista = saldosFiltrados();
    renderizarTabela({
        id: 'bank',
        chave: 'banco',
        linhas: lista,
        montarLinha: linhaDoBanco,
        mensagemVazia: saldosDoBanco().length ? 'Nenhum saldo para os filtros selecionados.' : 'Importe o relatório do banco de horas.',
        renderizar: renderizarBancoDeHoras,
    });
    document.getElementById('bank-export').disabled = lista.length === 0;
}

// Salva ao sair do campo. A tabela não é redesenhada: quem já está digitando
// na próxima observação não perde o que escreveu
async function salvarObservacaoDoBanco(campo) {
    const aberta = competencia;
    const matricula = campo.dataset.bankNote;
    const autoria = campo.parentElement.querySelector('.note-author');
    autoria.classList.remove('error');
    autoria.textContent = 'Salvando...';
    try {
        const dados = await requisitar(
            urlCom(OBSERVACOES_DO_BANCO_API_URL, aberta.competency.id), 'POST', { employee_id: matricula, note: campo.value },
        );
        // A mesma matrícula pode estar em mais de uma linha do relatório
        aberta.bank_hours.filter((saldo) => saldo.employee_id === matricula).forEach((saldo) => Object.assign(saldo, dados));
        autoria.textContent = autoriaDaObservacao(dados);
    } catch (erro) {
        autoria.classList.add('error');
        autoria.textContent = `Não foi possível salvar: ${erro.message}`;
    }
}

// Horas extras

function horasExtras() {
    return ocorrencias.filter((o) => [HORAS_EXTRAS, HORAS_EXTRAS_ACIMA_DE_2H].includes(o.type));
}

function horasExtrasDaLocalizacao() {
    const localizacao = document.getElementById('overtime-location').value;
    return horasExtras().filter((o) => !localizacao || o.location === localizacao);
}

function horasExtrasFiltradas() {
    const lista = filtrarPorBusca(horasExtrasDaLocalizacao(), 'overtime-search', 'overtime-kind');
    return ordenar(lista, document.getElementById('overtime-sort').value);
}

function renderizarHorasExtras() {
    // Os indicadores seguem só a localização; a busca e o tipo filtram a tabela
    const extras = horasExtrasDaLocalizacao();
    const colaboradores = (lista) => numero(new Set(lista.map((o) => o.employee_id)).size);
    document.getElementById('overtime-total').textContent = formatarHoras(extras.reduce((total, o) => total + o.minutes, 0));
    document.getElementById('overtime-people').textContent = colaboradores(extras);
    document.getElementById('overtime-long-people').textContent = colaboradores(extras.filter((o) => o.type === HORAS_EXTRAS_ACIMA_DE_2H));

    const lista = horasExtrasFiltradas();
    renderizarTabela({
        id: 'overtime',
        chave: 'extras',
        linhas: lista,
        montarLinha: (ocorrencia) => `
            <tr>
                <td>${dataBr(ocorrencia.day)}</td>
                <td>${escaparHtml(ocorrencia.employee_name)}</td>
                <td>${escaparHtml(ocorrencia.employee_id)}</td>
                <td>${escaparHtml(ocorrencia.location)}</td>
                <td><span class="badge ${ocorrencia.type === HORAS_EXTRAS_ACIMA_DE_2H ? 'high' : 'neutral'}">${formatarHoras(ocorrencia.minutes)}</span></td>
                <td>${escaparHtml(ocorrencia.scale || 'Não informada')}</td>
            </tr>`,
        mensagemVazia: mensagemSemDados('Nenhum registro de horas extras para os filtros selecionados.'),
        renderizar: renderizarHorasExtras,
    });
    document.getElementById('overtime-export').disabled = lista.length === 0;
}

// Rankings

const ORDENACOES_DO_RANKING = {
    count: (a, b) => b.count - a.count || b.minutes - a.minutes,
    minutes: (a, b) => b.minutes - a.minutes || b.count - a.count,
    location: ORDENACOES.location,
    name: ORDENACOES.name,
};

function renderizarRanking(chave) {
    const ranking = RANKINGS[chave];
    const localizacao = document.getElementById(`${chave}-location`).value;
    const busca = normalizar(document.getElementById(`${chave}-search`).value);
    const lista = (ranking.linhas || [])
        .filter((item) => (!localizacao || item.location === localizacao)
            && (!busca || normalizar(`${item.employee_name} ${item.employee_id} ${item.location}`).includes(busca)))
        .sort(ORDENACOES_DO_RANKING[document.getElementById(`${chave}-sort`).value]);
    renderizarTabela({
        id: chave,
        chave,
        linhas: lista,
        montarLinha: (item) => `
            <tr>
                <td class="person"><strong>${escaparHtml(item.employee_name)}</strong></td>
                <td>${escaparHtml(item.employee_id)}</td>
                <td>${escaparHtml(item.location)}</td>
                <td>${numero(item.count)}</td>
                <td>${formatarHoras(item.minutes)}</td>
            </tr>`,
        mensagemVazia: ranking.linhas === null
            ? 'Carregando...'
            : `Nenhuma ocorrência de ${tipo(ranking.tipo).label.toLowerCase()} para os filtros selecionados.`,
        renderizar: () => renderizarRanking(chave),
    });
}

async function carregarRanking(chave) {
    const ranking = RANKINGS[chave];
    const escopo = document.getElementById(`${chave}-scope`).value;
    const id = escopo === 'current' ? competencia && competencia.competency.id : escopo;
    const pedido = ++ranking.pedido;
    ranking.linhas = null;
    paginas[chave] = 1;
    renderizarRanking(chave);

    let linhas = [];
    if (id) {
        try {
            linhas = (await requisitar(urlDeIndicadores(id))).rankings[ranking.tipo];
        } catch (erro) {
            mostrarErro(erro.message);
        }
    }
    if (pedido !== ranking.pedido) return;
    ranking.linhas = linhas;
    preencherSelect(`${chave}-location`, 'Todas as localizações', opcoesDeLocalizacao(linhas));
    renderizarRanking(chave);
}

// Os indicadores vêm do servidor: carregam quando a aba abre e de novo quando
// os dados mudam com ela aberta
const INDICADORES_DAS_ABAS = {
    'ranking-intrajornada': () => carregarRanking('intra'),
    'ranking-interjornada': () => carregarRanking('inter'),
};

function abaAtual() {
    const ativa = document.querySelector('[data-tab].active');
    return ativa ? ativa.dataset.tab : null;
}

// Gráficos

function contagemPorLocalizacao() {
    const localizacoes = new Map();
    ocorrencias.forEach((ocorrencia) => {
        if (!localizacoes.has(ocorrencia.location)) {
            localizacoes.set(ocorrencia.location, { nome: ocorrencia.location, total: 0, tipos: {} });
        }
        const item = localizacoes.get(ocorrencia.location);
        item.total += 1;
        item.tipos[ocorrencia.type] = (item.tipos[ocorrencia.type] || 0) + 1;
    });
    return [...localizacoes.values()].sort((a, b) => b.total - a.total || a.nome.localeCompare(b.nome, 'pt-BR'));
}

function vazioDoGrafico() {
    return `<p class="empty">${competencia ? 'Sem ocorrências nesta competência.' : 'Importe os relatórios para gerar os indicadores.'}</p>`;
}

// A cor segue o tipo de ocorrência, sempre na ordem do catálogo: filtrar ou
// faltar um tipo não repinta os outros
function renderizarGraficoLocalizacoes(localizacoes) {
    const container = document.getElementById('chart-locations');
    const legenda = document.getElementById('chart-locations-legend');
    if (!localizacoes.length) {
        container.innerHTML = vazioDoGrafico();
        legenda.innerHTML = '';
        return;
    }

    const maximo = Math.max(...localizacoes.map((item) => item.total));
    container.innerHTML = localizacoes.map((localizacao) => {
        const presentes = catalogo.types.filter((item) => localizacao.tipos[item.code]);
        const resumo = presentes.map((item) => `${item.label}: ${localizacao.tipos[item.code]}`).join('; ');
        const segmentos = presentes.map((item) => `
            <span class="stack-segment serie-${tipos[item.code].serie}" style="flex-grow: ${localizacao.tipos[item.code]}"
                data-tooltip-value="${numero(localizacao.tipos[item.code])}"
                data-tooltip-label="${escaparHtml(`${item.label} · ${localizacao.nome}`)}"></span>`).join('');
        return `
            <button type="button" class="stack-row" data-filter-location="${escaparHtml(localizacao.nome)}"
                data-tooltip-value="${numero(localizacao.total)} ocorrências"
                data-tooltip-label="${escaparHtml(`${localizacao.nome} · ${resumo}`)}"
                aria-label="${escaparHtml(`${localizacao.nome}: ${localizacao.total} ocorrências. ${resumo}`)}">
                <span class="stack-name">${escaparHtml(localizacao.nome)}</span>
                <span class="stack-plot">
                    <span class="stack-bar" style="width: ${(localizacao.total / maximo * 100).toFixed(2)}%">${segmentos}</span>
                </span>
                <span class="stack-total">${numero(localizacao.total)}</span>
            </button>`;
    }).join('');

    legenda.innerHTML = catalogo.types
        .filter((item) => localizacoes.some((localizacao) => localizacao.tipos[item.code]))
        .map((item) => `
            <span class="legend-item">
                <i class="legend-swatch serie-${tipos[item.code].serie}" aria-hidden="true"></i>${escaparHtml(item.label)}
            </span>`).join('');
}

// Uma série só, numa cor só: o comprimento já diz qual tipo pesa mais
function renderizarGraficoTipos() {
    const container = document.getElementById('chart-types');
    const linhas = catalogo.types
        .map((item) => ({ ...item, total: contar(ocorrencias, (o) => o.type === item.code) }))
        .filter((item) => item.total)
        .sort((a, b) => b.total - a.total);
    if (!linhas.length) {
        container.innerHTML = vazioDoGrafico();
        return;
    }

    const maximo = linhas[0].total;
    container.innerHTML = linhas.map((item) => {
        const parte = Math.round(item.total / ocorrencias.length * 100);
        return `
            <button type="button" class="rank-row" data-filter-type="${item.code}"
                aria-label="${escaparHtml(`${item.label}: ${item.total} ocorrências, ${parte}% do total`)}">
                <span class="rank-name">${escaparHtml(item.label)}</span>
                <span class="rank-plot"><span class="rank-bar" style="width: ${(item.total / maximo * 100).toFixed(2)}%"></span></span>
                <span class="rank-value">${numero(item.total)} <span class="muted">· ${parte}%</span></span>
            </button>`;
    }).join('');
}

function renderizarGraficoTratativas() {
    const acionaveis = ocorrencias.filter((ocorrencia) => tipo(ocorrencia.type).actionable);
    const pendentes = contar(acionaveis, pendente);
    const concluidas = acionaveis.length - pendentes;
    const porcentagem = acionaveis.length ? Math.round(concluidas / acionaveis.length * 100) : 0;

    document.getElementById('chart-treatments').innerHTML = `
        <div class="meter-figure">
            <strong>${porcentagem}%</strong>
            <span class="muted">das tratativas obrigatórias concluídas</span>
        </div>
        <div class="meter" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${porcentagem}"
            aria-label="Tratativas obrigatórias concluídas"><span style="width: ${porcentagem}%"></span></div>
        <div class="meter-legend">
            <span><i class="fas fa-circle-check icon-done" aria-hidden="true"></i> ${numero(concluidas)} concluídas</span>
            <span><i class="fas fa-hourglass-half icon-pending" aria-hidden="true"></i> ${numero(pendentes)} pendentes</span>
        </div>
        <p class="muted">${acionaveis.length
            ? `${numero(concluidas)} de ${numero(acionaveis.length)} tratativas obrigatórias concluídas.`
            : 'Nenhuma tratativa obrigatória identificada nesta competência.'}</p>`;
}

function nivelDeCalor(valor, maximo) {
    return Math.max(1, Math.ceil(valor / maximo * NIVEIS_DE_CALOR));
}

// A matriz também é a tabela do gráfico de localizações: todo número aparece nela
function renderizarMapaDeCalor(localizacoes) {
    const container = document.getElementById('chart-heatmap');
    const escala = document.getElementById('chart-heatmap-scale');
    const presentes = catalogo.types.filter((item) => localizacoes.some((localizacao) => localizacao.tipos[item.code]));
    if (!localizacoes.length) {
        container.innerHTML = vazioDoGrafico();
        escala.innerHTML = '';
        return;
    }

    const maximo = Math.max(...localizacoes.flatMap((localizacao) => presentes.map((item) => localizacao.tipos[item.code] || 0)));
    const linhas = localizacoes.map((localizacao) => {
        const celulas = presentes.map((item) => {
            const valor = localizacao.tipos[item.code] || 0;
            if (!valor) return '<td><span class="heat-empty" aria-label="Nenhuma">—</span></td>';
            return `
                <td>
                    <button type="button" class="heat-cell heat-${nivelDeCalor(valor, maximo)}"
                        data-filter-location="${escaparHtml(localizacao.nome)}" data-filter-type="${item.code}"
                        data-tooltip-value="${numero(valor)}" data-tooltip-label="${escaparHtml(`${item.label} · ${localizacao.nome}`)}"
                        aria-label="${escaparHtml(`${localizacao.nome}, ${item.label}: ${valor}`)}">${numero(valor)}</button>
                </td>`;
        }).join('');
        return `
            <tr>
                <th scope="row">${escaparHtml(localizacao.nome)}</th>
                ${celulas}
                <td class="heat-total">${numero(localizacao.total)}</td>
            </tr>`;
    }).join('');

    container.innerHTML = `
        <table class="heatmap">
            <thead>
                <tr>
                    <th scope="col">Localização</th>
                    ${presentes.map((item) => `<th scope="col">${escaparHtml(item.label)}</th>`).join('')}
                    <th scope="col">Total</th>
                </tr>
            </thead>
            <tbody>${linhas}</tbody>
        </table>`;

    const niveis = Array.from({ length: NIVEIS_DE_CALOR }, (_, indice) => `<i class="heat-${indice + 1}" aria-hidden="true"></i>`);
    escala.innerHTML = `<span>Menos (1)</span>${niveis.join('')}<span>Mais (${numero(maximo)})</span>`;
}

function renderizarResumo() {
    const itens = [
        ['Registros analisados no Sumarizado', competencia ? competencia.analysed_rows : 0],
        ['Ocorrências totais', ocorrencias.length],
        ['Faltas a confirmar', contar(ocorrencias, (o) => o.type === FALTA && pendente(o))],
        ['Alertas de intervalo abaixo de 1h', contar(ocorrencias, (o) => o.type === INTERVALO_CURTO)],
        ['Horas extras acima de 2h', contar(ocorrencias, (o) => o.type === HORAS_EXTRAS_ACIMA_DE_2H)],
    ];
    document.getElementById('chart-summary').innerHTML = itens
        .map(([rotulo, valor]) => `<div><dt>${rotulo}</dt><dd>${numero(valor)}</dd></div>`)
        .join('');
}

function renderizarGraficos() {
    const localizacoes = contagemPorLocalizacao();
    const pendentes = contar(ocorrencias, pendente);
    document.getElementById('chart-kpi-total').textContent = numero(ocorrencias.length);
    document.getElementById('chart-kpi-pending').textContent = numero(pendentes);
    document.getElementById('chart-kpi-locations').textContent = numero(localizacoes.length);
    document.getElementById('chart-kpi-done').textContent = numero(contar(ocorrencias, concluida));

    renderizarGraficoLocalizacoes(localizacoes);
    renderizarGraficoTipos();
    renderizarGraficoTratativas();
    renderizarMapaDeCalor(localizacoes);
    renderizarResumo();
}

// A dica mostra o valor primeiro; os nomes vêm das planilhas e entram como texto
function configurarDicas() {
    const dica = document.getElementById('chart-tooltip');

    function mostrar(alvo, x, y) {
        const valor = document.createElement('strong');
        valor.textContent = alvo.dataset.tooltipValue;
        const rotulo = document.createElement('span');
        rotulo.textContent = alvo.dataset.tooltipLabel;
        dica.replaceChildren(valor, rotulo);
        dica.hidden = false;

        const { width, height } = dica.getBoundingClientRect();
        dica.style.left = `${Math.max(8, Math.min(x + 14, window.innerWidth - width - 8))}px`;
        dica.style.top = `${y - height - 12 < 8 ? y + 18 : y - height - 12}px`;
    }

    document.addEventListener('pointermove', (evento) => {
        const alvo = evento.target.closest('[data-tooltip-value]');
        if (alvo) mostrar(alvo, evento.clientX, evento.clientY);
        else dica.hidden = true;
    });
    document.addEventListener('focusin', (evento) => {
        const alvo = evento.target.closest('[data-tooltip-value]');
        if (!alvo) return;
        const area = alvo.getBoundingClientRect();
        mostrar(alvo, area.left + area.width / 2, area.top);
    });
    document.addEventListener('focusout', () => { dica.hidden = true; });
    window.addEventListener('scroll', () => { dica.hidden = true; }, { passive: true });
}

// Recorrência

function renderizarRecorrencia() {
    renderizarTabela({
        id: 'recurrence',
        chave: 'recorrencia',
        linhas: recorrencia || [],
        montarLinha: (colaborador) => {
            const classe = colaborador.count >= 3 ? 'high' : colaborador.count === 2 ? 'medium' : 'neutral';
            let acompanhamento = 'Monitorar';
            if (colaborador.count >= 3) acompanhamento = '<span class="attention">Avaliar plano de ação</span>';
            else if (colaborador.count === 2) acompanhamento = 'Acompanhar recorrência';
            return `
                <tr>
                    <td><strong>${escaparHtml(colaborador.employee_name)}</strong></td>
                    <td>${escaparHtml(colaborador.employee_id)}</td>
                    <td><span class="badge ${classe}">${numero(colaborador.count)}</span></td>
                    <td class="evidence">${colaborador.days.map(dataBr).join(', ')}</td>
                    <td>${numero(colaborador.adjustments)}</td>
                    <td>${acompanhamento}</td>
                </tr>`;
        },
        mensagemVazia: recorrencia === null
            ? 'Carregando...'
            : 'Ainda não há batidas ímpares nas competências salvas.',
        renderizar: renderizarRecorrencia,
    });
}

async function carregarRecorrencia() {
    renderizarRecorrencia();
    try {
        recorrencia = (await requisitar(RECORRENCIA_API_URL)).employees;
    } catch (erro) {
        mostrarErro(erro.message);
        recorrencia = recorrencia || [];
    }
    renderizarRecorrencia();
}

// Competências salvas

function renderizarCompetencias() {
    const aberta = competencia ? competencia.competency.id : null;
    document.querySelector('#competencies-table tbody').innerHTML = competencias.map((item) => {
        const relatorios = catalogo.reports;
        const etiquetas = Object.entries(relatorios).map(([codigo, rotulo]) => (item.reports.includes(codigo)
            ? `<span class="badge done"><i class="fas fa-check"></i>${escaparHtml(rotulo)}</span>`
            : `<span class="badge neutral"><i class="fas fa-minus"></i>${escaparHtml(rotulo)}</span>`)).join('');
        const conferencia = item.finished_at
            ? `<span class="badge done">Finalizada</span> <span class="muted">${escaparHtml(dataHoraBr(item.finished_at))}${item.finished_by ? ` · ${escaparHtml(item.finished_by)}` : ''}</span>`
            : '<span class="badge pending">Em andamento</span>';
        const acoes = [
            item.id === aberta
                ? '<span class="badge neutral">Aberta</span>'
                : `<button type="button" class="button small" data-open-competency="${item.id}">Abrir</button>`,
            permissoes.delete && `<button type="button" class="button small danger" data-delete-competency="${item.id}" title="Excluir competência"><i class="fas fa-trash"></i></button>`,
        ].filter(Boolean).join('');
        return `
            <tr>
                <td><strong>${escaparHtml(rotuloPeriodo(item.start_date, item.end_date))}</strong></td>
                <td><div class="report-chips">${etiquetas}</div></td>
                <td>${numero(item.occurrence_count)}</td>
                <td>${numero(item.pending_count)}</td>
                <td>${conferencia}</td>
                <td><div class="row-actions">${acoes}</div></td>
            </tr>`;
    }).join('');

    const vazio = document.getElementById('competencies-empty');
    vazio.hidden = competencias.length > 0;
    vazio.textContent = 'Nenhuma competência salva ainda. Importe os relatórios para criar a primeira.';
    document.getElementById('competencies-table').hidden = competencias.length === 0;
}

async function excluirCompetencia(id) {
    const item = competencias.find((competenciaSalva) => competenciaSalva.id === id);
    if (!item) return;
    const rotulo = rotuloPeriodo(item.start_date, item.end_date);
    if (!confirm(
        `ATENÇÃO: excluir a competência ${rotulo}? Isso apagará permanentemente os relatórios e as tratativas `
        + 'dessa competência. Esta ação não pode ser desfeita. Deseja continuar?',
    )) return;

    await requisitar(urlCom(COMPETENCIA_API_URL, id), 'DELETE');
    competencias = competencias.filter((competenciaSalva) => competenciaSalva.id !== id);
    recorrencia = null;
    if (competencia && competencia.competency.id === id) {
        definirCompetencia(null);
    } else {
        renderizarTudo();
    }
    mostrarSucesso(`Competência ${rotulo} excluída.`);
}

async function finalizarConferencia() {
    const pendentes = contar(ocorrencias, pendente);
    if (pendentes && !confirm(`${pendentes} tratativa(s) ainda estão pendentes. Deseja finalizar mesmo assim?`)) return;

    const dados = await requisitar(urlCom(FINALIZAR_API_URL, competencia.competency.id), 'POST', {});
    competencia.competency = dados.competency;
    mostrarSucesso('Conferência marcada como finalizada.');
    renderizarIndicadores();
    await atualizarCompetencias();
}

// Tratativa

function linhaHistorico(registro) {
    const resultado = registro.treatment
        ? catalogo.treatments[registro.treatment]
        : tipo(ocorrenciaAberta.type).pending_label;
    return `
        <tr>
            <td>${escaparHtml(dataHoraBr(registro.created_at))}</td>
            <td>${escaparHtml(resultado)}</td>
            <td>${escaparHtml(registro.responsible)}</td>
            <td>${escaparHtml(registro.user || '-')}</td>
            <td class="note">${escaparHtml(registro.note)}</td>
        </tr>`;
}

async function carregarHistorico(id) {
    const historico = document.getElementById('treatment-history');
    historico.innerHTML = '<p class="muted">Carregando...</p>';
    try {
        const dados = await requisitar(urlCom(TRATATIVAS_API_URL, id));
        if (!ocorrenciaAberta || ocorrenciaAberta.id !== id) return;
        historico.innerHTML = dados.treatments.length
            ? `
                <div class="table-wrapper">
                    <table>
                        <thead><tr><th>Data</th><th>Resultado</th><th>Responsável</th><th>Registrado por</th><th>Observação</th></tr></thead>
                        <tbody>${dados.treatments.map(linhaHistorico).join('')}</tbody>
                    </table>
                </div>`
            : '<p class="muted">Nenhuma tratativa registrada ainda.</p>';
    } catch (erro) {
        historico.innerHTML = `<p class="form-error">${escaparHtml(erro.message)}</p>`;
    }
}

function abrirOcorrencia(id) {
    const ocorrencia = ocorrencias.find((item) => item.id === id);
    if (!ocorrencia) return;
    ocorrenciaAberta = ocorrencia;
    const tipoOcorrencia = tipo(ocorrencia.type);

    document.getElementById('treatment-modal-title').textContent = tipoOcorrencia.label;
    document.getElementById('treatment-details').innerHTML = [
        ['Colaborador', `${ocorrencia.employee_name} (${ocorrencia.employee_id})`],
        ['Data', dataBr(ocorrencia.day)],
        ['Localização', ocorrencia.location],
        ['Escala', ocorrencia.scale || 'Não informada'],
        ['Evidência', ocorrencia.evidence],
        ['Tratativa atual', textoTratativa(ocorrencia)],
        ...(ocorrencia.note ? [['Observação', ocorrencia.note]] : []),
    ].map(([rotulo, valor]) => `<dt>${rotulo}</dt><dd>${escaparHtml(valor)}</dd>`).join('');

    const formulario = document.getElementById('treatment-form');
    if (formulario) {
        const resultado = document.getElementById('treatment-select');
        resultado.innerHTML = [
            `<option value="">${escaparHtml(tipoOcorrencia.pending_label)}</option>`,
            ...tipoOcorrencia.treatments.map((codigo) => `<option value="${codigo}">${escaparHtml(catalogo.treatments[codigo])}</option>`),
        ].join('');
        resultado.value = ocorrencia.treatment;
        document.getElementById('treatment-responsible').value = ocorrencia.responsible || responsavelPadrao;
        const observacao = document.getElementById('treatment-note');
        observacao.value = ocorrencia.note;
        observacao.placeholder = PLACEHOLDERS[ocorrencia.type] || 'Registre o que foi confirmado e a ação tomada.';
        document.getElementById('treatment-error').hidden = true;
    }

    document.getElementById('treatment-modal').showModal();
    if (formulario) document.getElementById('treatment-select').focus();
    carregarHistorico(ocorrencia.id);
}

function substituirOcorrencia(ocorrencia) {
    const indice = ocorrencias.findIndex((item) => item.id === ocorrencia.id);
    if (indice !== -1) ocorrencias[indice] = ocorrencia;
}

async function salvarTratativa(evento) {
    evento.preventDefault();
    if (!ocorrenciaAberta) return;

    const botao = evento.currentTarget.querySelector('button[type="submit"]');
    const erro = document.getElementById('treatment-error');
    const corpo = {
        treatment: document.getElementById('treatment-select').value,
        responsible: document.getElementById('treatment-responsible').value.trim(),
        note: document.getElementById('treatment-note').value.trim(),
    };
    const faltando = !corpo.note
        ? 'Registre uma observação antes de salvar a tratativa.'
        : !corpo.responsible && 'Informe quem realizou a conferência.';
    if (faltando) {
        erro.textContent = faltando;
        erro.hidden = false;
        return;
    }

    botao.disabled = true;
    try {
        erro.hidden = true;
        const dados = await requisitar(urlCom(TRATATIVAS_API_URL, ocorrenciaAberta.id), 'POST', corpo);
        substituirOcorrencia(dados.occurrence);
        recorrencia = null;
        document.getElementById('treatment-modal').close();
        mostrarErro('');
        mostrarSucesso('Tratativa e observação salvas no histórico da competência.');
        renderizarTudo();
        atualizarCompetencias().catch(() => {});
    } catch (falha) {
        // O erro fica no modal para a pessoa corrigir sem perder o que digitou
        erro.textContent = falha.message;
        erro.hidden = false;
    } finally {
        botao.disabled = false;
    }
}

// Exportação

function exportarPlanilha(nome, aba, cabecalho, linhas, larguras) {
    const planilha = XLSX.utils.aoa_to_sheet([cabecalho, ...linhas]);
    planilha['!cols'] = larguras.map((wch) => ({ wch }));
    const pasta = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(pasta, planilha, aba);
    XLSX.writeFile(pasta, `${nome}-${periodo.start_date}-a-${periodo.end_date}.xlsx`);
}

function exportarOcorrencias() {
    const cabecalho = [
        'Competência início', 'Competência fim', 'Data', 'Matrícula', 'Colaborador', 'Localização', 'Ocorrência',
        'Evidência', 'Prioridade', 'Tratativa', 'Observação', 'Responsável', 'Atualizado em', 'Escala',
    ];
    const linhas = ocorrenciasFiltradas().map((ocorrencia) => {
        const tipoOcorrencia = tipo(ocorrencia.type);
        return [
            dataBr(periodo.start_date), dataBr(periodo.end_date), dataBr(ocorrencia.day), ocorrencia.employee_id,
            ocorrencia.employee_name, ocorrencia.location, tipoOcorrencia.label, ocorrencia.evidence,
            tipoOcorrencia.priority, tipoOcorrencia.actionable ? textoTratativa(ocorrencia) : 'Informativo',
            ocorrencia.note, ocorrencia.responsible, dataHoraBr(ocorrencia.treated_at), ocorrencia.scale,
        ];
    });

    exportarPlanilha('auditoria-jornada', 'Ocorrências', cabecalho, linhas, [12, 12, 11, 11, 30, 22, 30, 60, 10, 26, 40, 22, 16, 30]);
}

function exportarBancoDeHoras() {
    const competenciaExportada = rotuloPeriodo(periodo.start_date, periodo.end_date);
    const linhas = saldosFiltrados().map((saldo) => [
        competenciaExportada, saldo.employee_name, saldo.employee_id, saldo.location, formatarHoras(saldo.balance), saldo.note,
    ]);
    exportarPlanilha(
        'banco-de-horas',
        'Banco de horas',
        ['Competência', 'Colaborador', 'Matrícula', 'Localização', 'Saldo', 'Observações / justificativas'],
        linhas,
        [24, 30, 11, 22, 10, 50],
    );
}

function exportarHorasExtras() {
    const competenciaExportada = rotuloPeriodo(periodo.start_date, periodo.end_date);
    const linhas = horasExtrasFiltradas().map((ocorrencia) => [
        competenciaExportada, dataBr(ocorrencia.day), ocorrencia.employee_name, ocorrencia.employee_id,
        ocorrencia.location, tipo(ocorrencia.type).label, formatarHoras(ocorrencia.minutes), ocorrencia.scale || 'Não informada',
    ]);
    exportarPlanilha(
        'horas-extras',
        'Horas extras',
        ['Competência', 'Data', 'Colaborador', 'Matrícula', 'Localização', 'Tipo de alerta', 'Horas extras', 'Escala'],
        linhas,
        [24, 11, 30, 11, 22, 24, 12, 30],
    );
}

// Navegação

function trocarAba(aba, atualizarEndereco = true) {
    const destino = ABAS.includes(aba) ? aba : ABAS[0];
    document.querySelectorAll('[data-tab]').forEach((botao) => {
        const ativa = botao.dataset.tab === destino;
        botao.classList.toggle('active', ativa);
        if (ativa) botao.setAttribute('aria-current', 'page');
        else botao.removeAttribute('aria-current');
    });
    document.querySelectorAll('[data-panel]').forEach((painel) => {
        painel.hidden = painel.dataset.panel !== destino;
    });
    // O replaceState troca o endereço sem rolar a página até a âncora
    if (atualizarEndereco) history.replaceState(null, '', `#${destino}`);

    if (destino === 'recorrencia') carregarRecorrencia();
    if (destino === 'competencias') atualizarCompetencias().catch((erro) => mostrarErro(erro.message));
    if (INDICADORES_DAS_ABAS[destino]) INDICADORES_DAS_ABAS[destino]();
}

function irParaIntervalos(tipoOcorrencia) {
    document.getElementById('interval-search').value = '';
    document.getElementById('interval-kind').value = tipoOcorrencia;
    paginas.intervalos = 1;
    renderizarIntervalos();
    trocarAba('intervalos');
}

const ATALHOS = {
    pending: () => irParaOcorrencias({ tratativa: 'pendentes' }),
    absences: () => irParaOcorrencias({ tipoOcorrencia: FALTA, tratativa: 'pendentes' }),
    'missing-break': () => irParaOcorrencias({ tipoOcorrencia: SEM_MARCACOES }),
    done: () => irParaOcorrencias({ tratativa: 'concluidas' }),
    'odd-punches': () => irParaOcorrencias({ tipoOcorrencia: BATIDAS_IMPARES }),
    'short-break': () => irParaIntervalos(INTERVALO_CURTO),
    'short-rest': () => irParaIntervalos(INTERJORNADA),
    'long-overtime': () => {
        document.getElementById('overtime-search').value = '';
        document.getElementById('overtime-location').value = '';
        document.getElementById('overtime-kind').value = HORAS_EXTRAS_ACIMA_DE_2H;
        paginas.extras = 1;
        renderizarHorasExtras();
        trocarAba('horas-extras');
    },
};

function aoClicar(evento) {
    const alvo = evento.target.closest(
        '[data-occurrence], [data-filter-type], [data-filter-location], [data-shortcut], [data-go-tab], '
        + '[data-open-competency], [data-delete-competency]',
    );
    if (!alvo) return;
    const { dataset } = alvo;

    if (dataset.occurrence) {
        abrirOcorrencia(Number(dataset.occurrence));
    } else if (dataset.filterType || dataset.filterLocation) {
        irParaOcorrencias({ tipoOcorrencia: dataset.filterType || '', localizacao: dataset.filterLocation || '' });
    } else if (dataset.shortcut) {
        ATALHOS[dataset.shortcut]();
    } else if (dataset.goTab) {
        trocarAba(dataset.goTab);
    } else if (dataset.openCompetency) {
        executar(async () => {
            await abrirCompetencia(Number(dataset.openCompetency));
            trocarAba('visao-geral');
        });
    } else if (dataset.deleteCompetency) {
        executar(() => excluirCompetencia(Number(dataset.deleteCompetency)));
    }
}

function renderizarTudo() {
    renderizarSeletorDeCompetencia();
    renderizarRelatorios();
    renderizarIndicadores();
    renderizarPrioritarios();
    atualizarFiltros();
    renderizarOcorrencias();
    renderizarIntervalos();
    renderizarBancoDeHoras();
    renderizarHorasExtras();
    renderizarGraficos();
    renderizarCompetencias();
    const aba = abaAtual();
    if (INDICADORES_DAS_ABAS[aba]) INDICADORES_DAS_ABAS[aba]();
}

document.addEventListener('DOMContentLoaded', () => {
    catalogo = lerJson('catalog-data');
    permissoes = lerJson('permissions-data');
    competencias = lerJson('competencies-data');
    responsavelPadrao = lerJson('responsible-data');
    periodo = lerJson('period-data');
    // Cada tipo fica com a sua série de cor, na ordem do catálogo
    catalogo.types.forEach((item, indice) => { tipos[item.code] = { ...item, serie: indice + 1 }; });

    montarFiltrosFixos();
    configurarDicas();
    document.addEventListener('click', aoClicar);

    document.querySelectorAll('[data-tab]').forEach((botao) => {
        botao.addEventListener('click', () => trocarAba(botao.dataset.tab));
    });

    document.getElementById('competency-select').addEventListener('change', (evento) => {
        if (evento.target.value) executar(() => abrirCompetencia(Number(evento.target.value)));
    });
    document.getElementById('open-period').addEventListener('click', () => executar(abrirPeriodo));
    // Trocar a data já abre o período, com uma folga para quem digita a data aos poucos
    ['start-date', 'end-date'].forEach((id) => {
        document.getElementById(id).addEventListener('change', () => {
            clearTimeout(temporizadorPeriodo);
            temporizadorPeriodo = setTimeout(() => executar(abrirPeriodo), 600);
        });
    });

    document.querySelectorAll('[data-report-input]').forEach((campo) => {
        campo.addEventListener('change', () => importarRelatorio(campo));
    });

    const aoFiltrarOcorrencias = () => {
        paginas.ocorrencias = 1;
        renderizarOcorrencias();
    };
    document.getElementById('occurrence-search').addEventListener('input', aoFiltrarOcorrencias);
    ['filter-employee', 'filter-type', 'filter-location', 'filter-priority', 'filter-treatment'].forEach((id) => {
        document.getElementById(id).addEventListener('change', aoFiltrarOcorrencias);
    });
    document.getElementById('clear-filters').addEventListener('click', () => {
        limparFiltros();
        renderizarOcorrencias();
    });
    document.getElementById('export-excel').addEventListener('click', exportarOcorrencias);

    const aoFiltrarIntervalos = () => {
        paginas.intervalos = 1;
        renderizarIntervalos();
    };
    document.getElementById('interval-search').addEventListener('input', aoFiltrarIntervalos);
    ['interval-kind', 'interval-sort'].forEach((id) => {
        document.getElementById(id).addEventListener('change', aoFiltrarIntervalos);
    });

    const aoFiltrarBanco = () => {
        paginas.banco = 1;
        renderizarBancoDeHoras();
    };
    document.getElementById('bank-search').addEventListener('input', aoFiltrarBanco);
    ['bank-location', 'bank-sort'].forEach((id) => {
        document.getElementById(id).addEventListener('change', aoFiltrarBanco);
    });
    document.getElementById('bank-export').addEventListener('click', exportarBancoDeHoras);
    document.getElementById('bank-table').addEventListener('change', (evento) => {
        if (evento.target.matches('[data-bank-note]')) salvarObservacaoDoBanco(evento.target);
    });

    const aoFiltrarHorasExtras = () => {
        paginas.extras = 1;
        renderizarHorasExtras();
    };
    document.getElementById('overtime-search').addEventListener('input', aoFiltrarHorasExtras);
    ['overtime-kind', 'overtime-location', 'overtime-sort'].forEach((id) => {
        document.getElementById(id).addEventListener('change', aoFiltrarHorasExtras);
    });
    document.getElementById('overtime-export').addEventListener('click', exportarHorasExtras);

    Object.keys(RANKINGS).forEach((chave) => {
        const aoFiltrarRanking = () => {
            paginas[chave] = 1;
            renderizarRanking(chave);
        };
        document.getElementById(`${chave}-scope`).addEventListener('change', () => carregarRanking(chave));
        document.getElementById(`${chave}-search`).addEventListener('input', aoFiltrarRanking);
        [`${chave}-location`, `${chave}-sort`].forEach((id) => {
            document.getElementById(id).addEventListener('change', aoFiltrarRanking);
        });
    });

    const botaoFinalizar = document.getElementById('finish-review');
    if (botaoFinalizar) botaoFinalizar.addEventListener('click', () => executar(finalizarConferencia));

    const modal = document.getElementById('treatment-modal');
    modal.querySelectorAll('[data-close-modal]').forEach((botao) => {
        botao.addEventListener('click', () => modal.close());
    });
    modal.addEventListener('close', () => { ocorrenciaAberta = null; });
    const formulario = document.getElementById('treatment-form');
    if (formulario) formulario.addEventListener('submit', salvarTratativa);

    const inicial = lerJson('competency-data');
    if (inicial) definirCompetencia(inicial);
    else renderizarTudo();
    trocarAba(window.location.hash.slice(1), false);
});
