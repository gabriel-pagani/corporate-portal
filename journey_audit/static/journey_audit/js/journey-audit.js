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
    evolutionUrl: EVOLUCAO_API_URL,
    employeeComparisonUrl: COMPARATIVO_POR_COLABORADOR_API_URL,
} = document.getElementById('content').dataset;

const ITENS_POR_PAGINA = 50;
const LIMITE_PRIORITARIOS = 8;
const NIVEIS_DE_CALOR = 6;
const ABAS = [
    'visao-geral', 'ocorrencias', 'intervalos', 'banco-de-horas', 'horas-extras', 'ranking-intrajornada',
    'ranking-interjornada', 'ranking-atestados', 'graficos', 'comparativo-ocorrencias', 'comparativo-colaborador',
    'recorrencia', 'competencias', 'importar', 'afastamentos',
];
const BANCO_DE_HORAS = 'B';
const SABADO = 6;

// Os códigos que a tela trata de forma especial; os rótulos vêm do catálogo
const BATIDAS_IMPARES = 'I';
const FALTA = 'F';
const SEM_MARCACOES = 'M';
const INTERVALO_CURTO = 'J';
const INTERJORNADA = 'N';
const HORAS_EXTRAS = 'E';
const HORAS_EXTRAS_ACIMA_DE_2H = 'H';
const TIPOS_DE_INTERVALO = [INTERVALO_CURTO, INTERJORNADA, SEM_MARCACOES];
const AFASTAMENTO_INFORMADO = 'A';
const TRATATIVAS_DESFAVORAVEIS = ['F', 'S'];
const NAO_PROCEDE = 'N';
const NAO_NECESSARIO = 'C';
const ORDEM_DE_PRIORIDADE = { Alta: 0, 'Média': 1, Baixa: 2 };

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
const paginas = {
    ocorrencias: 1, intervalos: 1, banco: 1, extras: 1, intra: 1, inter: 1, atestados: 1, recorrencia: 1,
    afastamentos: 1, comparaColaboradores: 1,
};

// Os relatórios escolhidos que esperam a confirmação, e o erro de cada um que
// a última importação recusou
const relatoriosProntos = new Map();
const errosDeImportacao = new Map();

// Os rankings vêm do servidor, que soma as competências; a localização, a busca
// e a ordem são aplicadas aqui. O pedido descarta a resposta que chega atrasada.
const RANKINGS = {
    intra: {
        linhas: null,
        pedido: 0,
        extrair: (dados) => dados.rankings[INTERVALO_CURTO],
        vazio: 'Nenhuma ocorrência de intrajornada inferior a 1h para os filtros selecionados.',
        montarLinha: linhaDoRankingDeIntervalo,
    },
    inter: {
        linhas: null,
        pedido: 0,
        extrair: (dados) => dados.rankings[INTERJORNADA],
        vazio: 'Nenhuma ocorrência de interjornada inferior a 11h para os filtros selecionados.',
        montarLinha: linhaDoRankingDeIntervalo,
    },
    atestados: {
        linhas: null,
        pedido: 0,
        extrair: (dados) => dados.medical_leaves,
        vazio: 'Nenhum atestado ou declaração para os filtros selecionados. '
            + 'Confira se o relatório de afastamentos foi importado e se cobre as datas da competência.',
        montarLinha: linhaDoRankingDeAtestados,
    },
};
const pedidosDeComparativo = { ocorrencias: 0, colaboradores: 0 };

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

// O mês de referência da folha, que é o do fim do período: 21/10 a 20/11 é a folha de 11/2026
function mesDaFolha(fim) {
    return dataBr(fim).slice(3);
}

function rotuloPeriodo(inicio, fim) {
    return `${dataBr(inicio)} a ${dataBr(fim)} — ${mesDaFolha(fim)}`;
}

// Ao meio-dia, para o fuso não puxar a data para o dia anterior
function diaDaSemana(iso) {
    return new Date(`${iso.slice(0, 10)}T12:00:00`).getDay();
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

// A prioridade vem do servidor em cada ocorrência: o mesmo tipo pode variar
// (o intervalo sem marcações da escala não identificada é média)
function prioridade(ocorrencia) {
    return ocorrencia.priority || tipo(ocorrencia.type).priority;
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
    dateDesc: (a, b) => b.day.localeCompare(a.day),
    name: (a, b) => comparar(a.employee_name, b.employee_name),
    location: (a, b) => comparar(a.location, b.location),
    type: (a, b) => comparar(tipo(a.type).label, tipo(b.type).label),
    priority: (a, b) => ORDEM_DE_PRIORIDADE[prioridade(a)] - ORDEM_DE_PRIORIDADE[prioridade(b)],
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
    const dados = await requisitar(urlCom(COMPETENCIA_API_URL, id));
    descartarRelatoriosProntos();
    definirCompetencia(dados);
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
    descartarRelatoriosProntos();
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
    situacao.innerHTML = competencia
        ? ''
        : `Nenhum relatório salvo para ${escaparHtml(rotuloPeriodo(periodo.start_date, periodo.end_date))}. `
          + '<button type="button" class="link-button" data-go-tab="importar">Importe os relatórios</button> para começar.';
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

function unidadeDoRelatorio(codigo) {
    return codigo === BANCO_DE_HORAS ? 'colaboradores' : 'linhas';
}

function renderizarRelatorios() {
    const relatorios = competencia ? competencia.reports : {};
    document.querySelectorAll('[data-report-state]').forEach((estado) => {
        const codigo = estado.dataset.reportState;
        const relatorio = relatorios[codigo];
        const pronto = relatoriosProntos.get(codigo);
        const erro = errosDeImportacao.get(codigo);
        estado.classList.toggle('error', Boolean(erro));
        estado.classList.toggle('ready', Boolean(pronto) && !erro);
        estado.classList.toggle('loaded', Boolean(relatorio) && !pronto && !erro);
        if (erro) {
            // O erro fica junto ao campo do relatório, para ficar claro qual arquivo recusou
            estado.textContent = `Erro: ${erro}`;
        } else if (pronto) {
            estado.textContent = `Arquivo pronto · ${pronto.name} · aguardando a confirmação da importação`;
        } else {
            estado.textContent = relatorio
                ? `✓ ${relatorio.file_name} · ${numero(relatorio.row_count)} ${unidadeDoRelatorio(codigo)} · `
                  + `enviado por ${relatorio.uploaded_by || 'usuário removido'} em ${dataHoraBr(relatorio.uploaded_at)}`
                : 'Nenhum relatório importado';
        }
    });

    const semSumarizado = competencia && !relatorios.S;
    document.getElementById('reports-hint').classList.toggle('attention', Boolean(semSumarizado));

    const confirmar = document.getElementById('confirm-import');
    if (!confirmar) return;
    confirmar.disabled = enviando || !relatoriosProntos.size;
    document.getElementById('import-state').textContent = relatoriosProntos.size
        ? `${relatoriosProntos.size} relatório(s) pronto(s) para ${rotuloPeriodo(periodo.start_date, periodo.end_date)}. `
          + 'Clique em confirmar para processar e salvar.'
        : 'Selecione os relatórios e confirme para processar e salvar.';
}

// Trocar de competência descarta o que foi escolhido para a outra
function descartarRelatoriosProntos() {
    relatoriosProntos.clear();
    errosDeImportacao.clear();
    document.querySelectorAll('[data-report-input]').forEach((campo) => { campo.value = ''; });
    const resumo = document.getElementById('import-summary');
    if (resumo) resumo.hidden = true;
}

function prepararRelatorio(campo) {
    const codigo = campo.dataset.reportInput;
    errosDeImportacao.delete(codigo);
    if (campo.files[0]) relatoriosProntos.set(codigo, campo.files[0]);
    else relatoriosProntos.delete(codigo);
    renderizarRelatorios();
}

function enviarRelatorio(codigo, arquivo) {
    const corpo = new FormData();
    corpo.append('start_date', periodo.start_date);
    corpo.append('end_date', periodo.end_date);
    corpo.append('type', codigo);
    corpo.append('file', arquivo);
    return requisitar(RELATORIOS_API_URL, 'POST', corpo);
}

function travarImportacao(travar) {
    enviando = travar;
    document.querySelectorAll('[data-report-input]').forEach((item) => { item.disabled = travar; });
}

// Os relatórios vão um a um: cada um é salvo e analisado com os que já estão
// na competência. O que o servidor recusa não impede os demais.
async function processarRelatorios() {
    if (enviando || !relatoriosProntos.size) return;
    const fila = [...relatoriosProntos.entries()];
    const resumo = document.getElementById('import-summary');
    travarImportacao(true);
    mostrarErro('');
    mostrarSucesso('');
    resumo.hidden = true;
    document.getElementById('confirm-import').disabled = true;
    document.getElementById('import-state').innerHTML = '<i class="fas fa-spinner fa-spin"></i> Importando e analisando os relatórios...';

    const resultados = [];
    let dados = null;
    for (const [codigo, arquivo] of fila) {
        const estado = document.querySelector(`[data-report-state="${codigo}"]`);
        estado.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Importando e analisando...';
        try {
            dados = await enviarRelatorio(codigo, arquivo);
            resultados.push({ codigo, arquivo: arquivo.name, linhas: dados.reports[codigo].row_count });
        } catch (erro) {
            resultados.push({ codigo, arquivo: arquivo.name, erro: erro.message });
            errosDeImportacao.set(codigo, erro.message);
        }
        relatoriosProntos.delete(codigo);
        document.querySelector(`[data-report-input="${codigo}"]`).value = '';
    }

    travarImportacao(false);
    if (dados) {
        recorrencia = null;
        definirCompetencia(dados);
        atualizarCompetencias().catch((erro) => mostrarErro(erro.message));
    } else {
        renderizarRelatorios();
    }
    renderizarResumoDaImportacao(resultados, dados);
}

function renderizarResumoDaImportacao(resultados, dados) {
    const salvos = resultados.filter((item) => !item.erro);
    const itens = resultados.map((item) => {
        const rotulo = `${catalogo.reports[item.codigo]}: ${item.arquivo}`;
        return item.erro
            ? `<li class="failed"><i class="fas fa-circle-xmark" aria-hidden="true"></i> ${escaparHtml(rotulo)} — não importado: ${escaparHtml(item.erro)}</li>`
            : `<li><i class="fas fa-circle-check" aria-hidden="true"></i> ${escaparHtml(rotulo)} — ${numero(item.linhas)} ${unidadeDoRelatorio(item.codigo)} processadas</li>`;
    }).join('');

    let conclusao = 'Nenhum relatório foi salvo. Corrija os arquivos indicados e selecione-os de novo.';
    if (salvos.length) {
        conclusao = `${salvos.length} de ${resultados.length} relatório(s) salvo(s) no portal e compartilhado(s) com quem acessa a auditoria. `
            + `A competência ${rotuloPeriodo(periodo.start_date, periodo.end_date)} tem ${numero(dados.occurrences.length)} ocorrências.`;
    }

    const resumo = document.getElementById('import-summary');
    resumo.classList.toggle('partial', salvos.length !== resultados.length);
    resumo.innerHTML = `
        <strong>${salvos.length === resultados.length ? '✓ Processamento concluído' : 'Processamento concluído com erros'}</strong>
        <ul>${itens}</ul>
        <p>${escaparHtml(conclusao)}</p>`;
    resumo.hidden = false;

    if (salvos.length === resultados.length) {
        mostrarSucesso(`Relatórios processados e salvos no portal: ${salvos.map((item) => item.arquivo).join(', ')}.`);
    } else {
        mostrarErro('Nem todos os relatórios foram importados. Confira o resumo na aba Importar Relatórios.');
    }
}

// O banco de horas, na aba dele, é importado assim que o arquivo é escolhido
async function importarBancoDeHoras(campo) {
    const arquivo = campo.files[0];
    if (!arquivo) return;
    if (enviando) {
        campo.value = '';
        return;
    }

    const estado = document.querySelector(`[data-report-state="${BANCO_DE_HORAS}"]`);
    travarImportacao(true);
    mostrarErro('');
    mostrarSucesso('');
    errosDeImportacao.delete(BANCO_DE_HORAS);
    estado.classList.remove('loaded', 'error');
    estado.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Importando...';
    try {
        const dados = await enviarRelatorio(BANCO_DE_HORAS, arquivo);
        travarImportacao(false);
        definirCompetencia(dados);
        mostrarSucesso(`Banco de horas importado e salvo no portal: ${arquivo.name} · `
            + `${numero(dados.reports[BANCO_DE_HORAS].row_count)} colaboradores com saldo.`);
        atualizarCompetencias().catch((erro) => mostrarErro(erro.message));
    } catch (erro) {
        travarImportacao(false);
        errosDeImportacao.set(BANCO_DE_HORAS, erro.message);
        renderizarRelatorios();
    } finally {
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
        'kpi-missing-break': contar(ocorrencias, (o) => o.type === SEM_MARCACOES && o.treatment !== NAO_NECESSARIO),
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

    // Sem o relatório do banco de horas ou de afastamentos, o indicador fica em branco
    const saldos = saldosDoBanco();
    const totais = totaisDoBanco(saldos);
    [['kpi-bank-positive', totais.positivo], ['kpi-bank-negative', totais.negativo], ['kpi-bank-hours', totais.liquido]]
        .forEach(([id, valor]) => { document.getElementById(id).textContent = saldos.length ? formatarHoras(valor) : '—'; });
    document.getElementById('kpi-overtime').textContent = formatarHoras(horasExtras().reduce((total, o) => total + o.minutes, 0));

    const afastamentos = competencia && competencia.leaves;
    document.getElementById('kpi-medical').textContent = afastamentos ? numero(contar(afastamentos.events, (a) => a.medical)) : '—';
    document.getElementById('kpi-leaves').textContent = afastamentos ? numero(afastamentos.events.length) : '—';
    document.getElementById('kpi-leave-days').textContent = afastamentos ? numero(afastamentos.days) : '—';

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
    const casos = ocorrencias
        .filter(pendente)
        .sort((a, b) => ORDENACOES.priority(a, b) || a.day.localeCompare(b.day))
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
    const afastamentos = afastamentosDoMes();
    preencherSelect(
        'leaves-type',
        'Todos os tipos de afastamento',
        [...new Set(afastamentos.map((afastamento) => afastamento.reason))].sort(comparar).map((motivo) => [motivo, motivo]),
    );
    preencherSelect('leaves-location', 'Todas as localizações', opcoesDeLocalizacao(afastamentos));
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
    const prioridadeFiltro = document.getElementById('filter-priority').value;
    const tratativa = document.getElementById('filter-treatment').value;

    const filtradas = ocorrencias.filter((ocorrencia) => {
        if (colaborador && ocorrencia.employee_id !== colaborador) return false;
        if (tipoFiltro && ocorrencia.type !== tipoFiltro) return false;
        if (localizacao && ocorrencia.location !== localizacao) return false;
        if (prioridadeFiltro && prioridade(ocorrencia) !== prioridadeFiltro) return false;
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
    return ordenar(filtradas, document.getElementById('occurrence-sort').value);
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
            <td>${badgePrioridade(prioridade(ocorrencia))}</td>
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

function totaisDoBanco(saldos) {
    const somar = (lista) => lista.reduce((total, saldo) => total + saldo.balance, 0);
    const positivo = somar(saldos.filter((saldo) => saldo.balance > 0));
    const negativo = somar(saldos.filter((saldo) => saldo.balance < 0));
    return { positivo, negativo, liquido: positivo + negativo };
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
        ? `<div class="bank-note-editor">
               <textarea class="bank-note" data-bank-note="${escaparHtml(saldo.employee_id)}" rows="2"
                   aria-label="${escaparHtml(`Observações para ${saldo.employee_name}`)}"
                   placeholder="Justificativa solicitada, retorno do supervisor...">${escaparHtml(saldo.note)}</textarea>
               <button type="button" class="button small" data-save-bank-note>Salvar</button>
           </div>`
        : `<span class="note-text">${escaparHtml(saldo.note || '—')}</span>`;
    let classe = 'neutral';
    if (saldo.balance < 0) classe = 'high';
    else if (saldo.balance > 0) classe = 'positive';
    return `
        <tr>
            <td class="person"><strong>${escaparHtml(saldo.employee_name)}</strong></td>
            <td>${escaparHtml(saldo.employee_id)}</td>
            <td>${escaparHtml(saldo.location)}</td>
            <td><span class="badge ${classe}">${formatarHoras(saldo.balance)}</span></td>
            <td class="bank-note-cell">${observacao}<div class="note-author">${escaparHtml(autoriaDaObservacao(saldo))}</div></td>
        </tr>`;
}

function renderizarBancoDeHoras() {
    // Os totais seguem só a localização; a busca filtra a tabela
    const saldos = saldosDaLocalizacao();
    const totais = totaisDoBanco(saldos);
    document.getElementById('bank-net').textContent = formatarHoras(totais.liquido);
    document.getElementById('bank-positive').textContent = formatarHoras(totais.positivo);
    document.getElementById('bank-negative').textContent = formatarHoras(totais.negativo);
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

// Salva ao sair do campo ou no botão Salvar; o que já está salvo não vai de
// novo. A tabela não é redesenhada: quem já está digitando na próxima
// observação não perde o que escreveu
async function salvarObservacaoDoBanco(campo) {
    const aberta = competencia;
    const matricula = campo.dataset.bankNote;
    const autoria = campo.closest('td').querySelector('.note-author');
    const salvo = aberta.bank_hours.find((saldo) => saldo.employee_id === matricula);
    if (salvo && salvo.note === campo.value.trim() && !autoria.classList.contains('error')) {
        autoria.textContent = autoriaDaObservacao(salvo) || 'Nada a salvar.';
        return;
    }
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
        // O sábado só ganha a etiqueta ao lado da data, sem destacar a linha
        montarLinha: (ocorrencia) => `
            <tr>
                <td class="nowrap">${dataBr(ocorrencia.day)}${diaDaSemana(ocorrencia.day) === SABADO ? ' <span class="badge neutral">Sábado</span>' : ''}</td>
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

// O ranking de atestados não tem minutos: o desempate é pelos dias de afastamento
const ORDENACOES_DO_RANKING = {
    count: (a, b) => b.count - a.count || (b.minutes ?? b.days) - (a.minutes ?? a.days) || ORDENACOES.name(a, b),
    minutes: (a, b) => b.minutes - a.minutes || b.count - a.count,
    days: (a, b) => b.days - a.days || b.count - a.count || ORDENACOES.name(a, b),
    id: (a, b) => a.employee_id.localeCompare(b.employee_id, 'pt-BR', { numeric: true }),
    reason: (a, b) => comparar(a.reasons.join('; '), b.reasons.join('; ')),
    location: ORDENACOES.location,
    name: ORDENACOES.name,
};

function linhaDoRankingDeIntervalo(item) {
    return `
        <tr>
            <td class="person"><strong>${escaparHtml(item.employee_name)}</strong></td>
            <td>${escaparHtml(item.employee_id)}</td>
            <td>${escaparHtml(item.location)}</td>
            <td>${numero(item.count)}</td>
            <td>${formatarHoras(item.minutes)}</td>
        </tr>`;
}

function linhaDoRankingDeAtestados(item) {
    return `
        <tr>
            <td class="person"><strong>${escaparHtml(item.employee_name)}</strong></td>
            <td>${escaparHtml(item.employee_id)}</td>
            <td>${escaparHtml(item.location)}</td>
            <td>${numero(item.count)}</td>
            <td>${numero(item.days)}</td>
            <td class="evidence">${escaparHtml(item.reasons.join('; '))}</td>
        </tr>`;
}

function renderizarRanking(chave) {
    const ranking = RANKINGS[chave];
    const localizacao = document.getElementById(`${chave}-location`).value;
    const busca = normalizar(document.getElementById(`${chave}-search`).value);
    const lista = (ranking.linhas || [])
        .filter((item) => (!localizacao || item.location === localizacao)
            && (!busca || normalizar(`${item.employee_name} ${item.employee_id} ${item.location} ${(item.reasons || []).join(' ')}`).includes(busca)))
        .sort(ORDENACOES_DO_RANKING[document.getElementById(`${chave}-sort`).value]);
    renderizarTabela({
        id: chave,
        chave,
        linhas: lista,
        montarLinha: ranking.montarLinha,
        mensagemVazia: ranking.linhas === null ? 'Carregando...' : ranking.vazio,
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
            linhas = ranking.extrair(await requisitar(urlDeIndicadores(id)));
        } catch (erro) {
            mostrarErro(erro.message);
        }
    }
    if (pedido !== ranking.pedido) return;
    ranking.linhas = linhas;
    preencherSelect(`${chave}-location`, 'Todas as localizações', opcoesDeLocalizacao(linhas));
    renderizarRanking(chave);
}

// Comparativos

// As competências marcadas em cada comparativo. Todas começam marcadas, e a
// competência que aparece depois (uma importação nova) entra marcada; a que a
// pessoa desmarcou continua desmarcada.
const competenciasMarcadas = { ocorrencias: new Set(), colaboradores: new Set() };
const competenciasConhecidas = { ocorrencias: new Set(), colaboradores: new Set() };

function competenciasEmOrdem() {
    return [...competencias].sort((a, b) => a.start_date.localeCompare(b.start_date) || a.end_date.localeCompare(b.end_date));
}

function competenciasEscolhidas(chave) {
    return competenciasEmOrdem().filter((item) => competenciasMarcadas[chave].has(String(item.id)));
}

function renderizarCaixasDeCompetencia(chave, id) {
    competencias.forEach((item) => {
        const valor = String(item.id);
        if (!competenciasConhecidas[chave].has(valor)) {
            competenciasConhecidas[chave].add(valor);
            competenciasMarcadas[chave].add(valor);
        }
    });
    document.getElementById(id).innerHTML = competencias.length
        ? competenciasEmOrdem().map((item) => `
            <label title="${escaparHtml(rotuloPeriodo(item.start_date, item.end_date))}">
                <input type="checkbox" value="${item.id}" data-compare-check="${chave}"${competenciasMarcadas[chave].has(String(item.id)) ? ' checked' : ''}>
                ${escaparHtml(mesDaFolha(item.end_date))}
            </label>`).join('')
        : '<span class="muted">Nenhuma competência salva.</span>';
}

// Os totais de cada competência vêm prontos do servidor, da mais antiga à mais
// recente. Cada tipo de ocorrência é um indicador, menos as tratativas de
// conferência (faltas e intervalos sem marcações) e os afastamentos informados;
// os atestados e o banco de horas ficam sem valor na competência sem o relatório deles.
const TIPOS_FORA_DO_COMPARATIVO = [FALTA, SEM_MARCACOES, AFASTAMENTO_INFORMADO];
let evolucao = null;

function indicadoresDaEvolucao() {
    const informado = (valor) => valor !== null && valor !== undefined;
    return [
        ...catalogo.types.filter((item) => !TIPOS_FORA_DO_COMPARATIVO.includes(item.code)).map((item) => ({
            chave: item.code,
            rotulo: item.label,
            formatar: numero,
            valor: (linha) => linha.types[item.code] || 0,
            presente: (linha) => Boolean(linha.types[item.code]),
        })),
        { chave: 'medical', rotulo: 'Atestados e declarações', formatar: numero, valor: (linha) => linha.medical_leaves },
        { chave: 'bank', rotulo: 'Saldo do banco de horas', formatar: formatarHoras, valor: (linha) => linha.bank_hours },
        { chave: 'bank-positive', rotulo: 'Banco de horas positivo', formatar: formatarHoras, valor: (linha) => linha.bank_positive },
        { chave: 'bank-negative', rotulo: 'Banco de horas negativo', formatar: formatarHoras, valor: (linha) => linha.bank_negative },
    ].map((indicador) => ({ presente: (linha) => informado(indicador.valor(linha)), ...indicador }));
}

// Todos os indicadores num gráfico só, uma linha por indicador. As cores são as
// das séries do projeto (.serie-N): cada tipo fica com a sua, na ordem do
// catálogo, e os indicadores do banco e dos atestados vêm depois. O banco de
// horas entra no eixo em horas, para não achatar as contagens; a dica mostra o
// valor em HH:MM.
const CORES_DAS_SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948', '#898781', '#0d8c9c'];
const GRAFICO = { largura: 1000, altura: 360, esquerda: 56, direita: 24, topo: 16, base: 40 };
const MAXIMO_DE_ROTULOS = 12;
const MARCAS_DO_EIXO = 5;

function corDoIndicador(indicador, indice) {
    const serie = tipos[indicador.chave] ? tipos[indicador.chave].serie : catalogo.types.length + indice + 1;
    return CORES_DAS_SERIES[(serie - 1) % CORES_DAS_SERIES.length];
}

function valorNoEixo(indicador, valor) {
    return indicador.formatar === formatarHoras ? valor / 60 : valor;
}

function passoDoEixo(faixa) {
    const bruto = faixa / MARCAS_DO_EIXO;
    const potencia = 10 ** Math.floor(Math.log10(bruto));
    return [1, 2, 2.5, 5, 10].map((fator) => fator * potencia).find((passo) => passo >= bruto);
}

function graficoDeEvolucao(indicadores, linhasDoGrafico) {
    const { largura, altura, esquerda, direita, topo, base } = GRAFICO;
    const series = indicadores.map((indicador, indice) => ({
        indicador,
        cor: corDoIndicador(indicador, indice - indicadores.filter((item) => tipos[item.chave]).length),
        pontos: linhasDoGrafico.map((item, posicao) => {
            const valor = indicador.valor(item);
            return { item, posicao, valor: valor ?? null, eixo: valor === null || valor === undefined ? null : valorNoEixo(indicador, valor) };
        }),
    }));
    const valores = series.flatMap((serie) => serie.pontos.filter((ponto) => ponto.eixo !== null).map((ponto) => ponto.eixo));

    // A escala sempre passa pelo zero, em passos redondos
    const passo = passoDoEixo((Math.max(0, ...valores) - Math.min(0, ...valores)) || 1);
    const minimo = Math.floor(Math.min(0, ...valores) / passo) * passo;
    const maximo = Math.ceil(Math.max(0, ...valores) / passo) * passo || passo;
    const larguraUtil = largura - esquerda - direita;
    const alturaUtil = altura - topo - base;
    const quantidade = linhasDoGrafico.length;
    const x = (posicao) => esquerda + (quantidade === 1 ? larguraUtil / 2 : posicao * larguraUtil / (quantidade - 1));
    const y = (valor) => topo + (maximo - valor) / (maximo - minimo) * alturaUtil;

    const grade = [];
    for (let marca = minimo; marca <= maximo + passo / 2; marca += passo) {
        grade.push(`
            <line x1="${esquerda}" x2="${largura - direita}" y1="${y(marca)}" y2="${y(marca)}" class="${marca === 0 ? 'evolution-zero' : 'evolution-grid-line'}"/>
            <text x="${esquerda - 8}" y="${y(marca) + 4}" text-anchor="end" class="evolution-axis">${numero(marca)}</text>`);
    }

    // Com muitas competências, os rótulos do eixo saltam algumas, sempre mostrando a última
    const salto = Math.ceil(quantidade / MAXIMO_DE_ROTULOS);
    const eixo = linhasDoGrafico
        .map((item, posicao) => ({ item, posicao }))
        .filter(({ posicao }) => (quantidade - 1 - posicao) % salto === 0)
        .map(({ item, posicao }) => `<text x="${x(posicao)}" y="${altura - 12}" text-anchor="middle" class="evolution-axis">${mesDaFolha(item.end_date)}</text>`)
        .join('');

    const desenhos = series.map(({ indicador, cor, pontos }) => {
        // A competência sem o relatório interrompe a linha
        const trechos = [];
        pontos.forEach((ponto) => {
            if (ponto.eixo === null) trechos.push([]);
            else {
                if (!trechos.length) trechos.push([]);
                trechos[trechos.length - 1].push(`${x(ponto.posicao)},${y(ponto.eixo)}`);
            }
        });
        const linhas = trechos.filter((trecho) => trecho.length > 1)
            .map((trecho) => `<polyline points="${trecho.join(' ')}" class="evolution-line" style="stroke: ${cor}"/>`).join('');
        const marcadores = pontos.filter((ponto) => ponto.eixo !== null).map((ponto) => {
            const periodoDoPonto = rotuloPeriodo(ponto.item.start_date, ponto.item.end_date);
            return `
                <g class="evolution-point" tabindex="0" role="img"
                    data-tooltip-value="${escaparHtml(indicador.formatar(ponto.valor))}"
                    data-tooltip-label="${escaparHtml(`${indicador.rotulo} · ${periodoDoPonto}`)}"
                    aria-label="${escaparHtml(`${indicador.rotulo} em ${periodoDoPonto}: ${indicador.formatar(ponto.valor)}`)}">
                    <circle cx="${x(ponto.posicao)}" cy="${y(ponto.eixo)}" r="12" class="evolution-hit"/>
                    <circle cx="${x(ponto.posicao)}" cy="${y(ponto.eixo)}" r="5" class="evolution-dot" style="fill: ${cor}"/>
                </g>`;
        }).join('');
        return linhas + marcadores;
    }).join('');

    const legenda = series.map(({ indicador, cor }) => `
        <span class="legend-item">
            <i class="legend-swatch" style="background-color: ${cor}" aria-hidden="true"></i>${escaparHtml(indicador.rotulo)}${indicador.formatar === formatarHoras ? ' (em horas)' : ''}
        </span>`).join('');

    return `
        <figure class="evolution-chart evolution-single">
            <svg viewBox="0 0 ${largura} ${altura}" aria-label="Evolução mensal por tipo de ocorrência e banco de horas">
                ${grade.join('')}${eixo}${desenhos}
            </svg>
            <div class="chart-legend">${legenda}</div>
        </figure>`;
}

// A mesma informação dos gráficos, em tabela
function tabelaDeEvolucao(indicadores, linhasDaTabela) {
    const cabecalho = indicadores.map(({ rotulo }) => `<th>${escaparHtml(rotulo)}</th>`).join('');
    const linhas = linhasDaTabela.map((item) => `
        <tr>
            <td>${escaparHtml(rotuloPeriodo(item.start_date, item.end_date))}</td>
            ${indicadores.map(({ formatar, valor }) => {
                const conteudo = valor(item);
                return `<td>${conteudo === null || conteudo === undefined ? '—' : escaparHtml(formatar(conteudo))}</td>`;
            }).join('')}
        </tr>`).join('');
    return `
        <details class="evolution-table">
            <summary>Ver os valores em tabela</summary>
            <div class="table-wrapper">
                <table><thead><tr><th>Competência</th>${cabecalho}</tr></thead><tbody>${linhas}</tbody></table>
            </div>
        </details>`;
}

function renderizarEvolucao() {
    renderizarCaixasDeCompetencia('ocorrencias', 'sector-competencies');
    const graficos = document.getElementById('evolution-charts');
    const vazio = document.getElementById('evolution-empty');
    const marcadas = new Set(competenciasEscolhidas('ocorrencias').map((item) => item.id));
    const linhas = (evolucao || []).filter((item) => marcadas.has(item.id));

    // O filtro oferece só os indicadores com algum dado nas competências escolhidas
    const disponiveis = indicadoresDaEvolucao().filter((indicador) => linhas.some(indicador.presente));
    preencherSelect('sector-indicator', 'Todos os indicadores', disponiveis.map((indicador) => [indicador.chave, indicador.rotulo]));
    const escolhido = document.getElementById('sector-indicator').value;
    const visiveis = disponiveis.filter((indicador) => !escolhido || indicador.chave === escolhido);

    const temDados = Boolean(linhas.length && visiveis.length);
    graficos.innerHTML = temDados
        ? graficoDeEvolucao(visiveis, linhas) + tabelaDeEvolucao(visiveis, linhas)
        : '';
    graficos.hidden = !temDados;
    vazio.hidden = temDados;
    if (evolucao === null) vazio.textContent = 'Carregando...';
    else if (!evolucao.length) vazio.textContent = 'Nenhuma competência salva ainda.';
    else if (!linhas.length) vazio.textContent = 'Marque pelo menos uma competência para comparar.';
    else vazio.textContent = 'Não há ocorrências nem banco de horas nas competências escolhidas.';
}

async function carregarComparativoDeOcorrencias() {
    const pedido = ++pedidosDeComparativo.ocorrencias;
    evolucao = null;
    renderizarEvolucao();

    let dados = [];
    try {
        dados = (await requisitar(EVOLUCAO_API_URL)).competencies;
    } catch (erro) {
        mostrarErro(erro.message);
    }
    if (pedido !== pedidosDeComparativo.ocorrencias) return;
    evolucao = dados;
    renderizarEvolucao();
}

// O comparativo por colaborador vem do servidor, já com só quem tem registro
// nas competências escolhidas; o colaborador e a localização filtram aqui
let comparativoPorColaborador = null;

function valorDoComparativo(valor, indicador) {
    // O banco de horas sem valor é a competência sem o relatório dele, ou sem o colaborador nele
    if (valor === undefined && indicador === 'bank') return '—';
    return ['extra', 'bank'].includes(indicador) ? formatarHoras(valor || 0) : numero(valor || 0);
}

function linhaDoComparativoPorColaborador(item) {
    const { indicador, competencias: colunas } = comparativoPorColaborador;
    const valores = colunas.map((coluna) => {
        const dias = item.days[coluna.id];
        return `<td>${valorDoComparativo(item.values[coluna.id], indicador)}${dias ? `<div class="muted">${numero(dias)} ${dias === 1 ? 'dia' : 'dias'}</div>` : ''}</td>`;
    }).join('');
    return `
        <tr>
            <td class="person"><strong>${escaparHtml(item.employee_name)}</strong></td>
            <td>${escaparHtml(item.employee_id)}</td>
            <td>${escaparHtml(item.location)}</td>
            <td class="evidence">${escaparHtml(item.types.join('; ') || '—')}</td>
            ${valores}
        </tr>`;
}

function renderizarComparativoPorColaborador() {
    const dados = comparativoPorColaborador;
    const colaborador = document.getElementById('employee-filter').value;
    const localizacao = document.getElementById('employee-location').value;
    const colunas = dados ? dados.competencias : [];
    document.querySelector('#compare-employees-table thead').innerHTML = `
        <tr>
            <th>Colaborador</th>
            <th>Matrícula</th>
            <th>Localização</th>
            <th>Tipo de ocorrência</th>
            ${colunas.map((coluna) => `<th title="${escaparHtml(rotuloPeriodo(coluna.start_date, coluna.end_date))}">${mesDaFolha(coluna.end_date)}</th>`).join('')}
        </tr>`;

    const linhas = (dados ? dados.employees : [])
        .filter((item) => (!colaborador || item.employee_id === colaborador) && (!localizacao || item.location === localizacao));
    let mensagem = 'Nenhum colaborador encontrado para os filtros selecionados.';
    if (dados === null) mensagem = 'Carregando...';
    else if (!competencias.length) mensagem = 'Nenhuma competência salva para comparar.';
    else if (!colunas.length) mensagem = 'Marque pelo menos uma competência para comparar.';

    renderizarTabela({
        id: 'compare-employees',
        chave: 'comparaColaboradores',
        linhas,
        montarLinha: linhaDoComparativoPorColaborador,
        mensagemVazia: mensagem,
        renderizar: renderizarComparativoPorColaborador,
    });
}

async function carregarComparativoPorColaborador() {
    renderizarCaixasDeCompetencia('colaboradores', 'employee-competencies');
    const pedido = ++pedidosDeComparativo.colaboradores;
    const escolhidas = competenciasEscolhidas('colaboradores');
    const indicador = document.getElementById('employee-indicator').value;
    comparativoPorColaborador = null;
    paginas.comparaColaboradores = 1;
    renderizarComparativoPorColaborador();

    const dados = { indicador, competencias: escolhidas, employees: [] };
    if (escolhidas.length) {
        const parametros = new URLSearchParams({ indicator: indicador });
        escolhidas.forEach((item) => parametros.append('competencies', item.id));
        try {
            dados.employees = (await requisitar(`${COMPARATIVO_POR_COLABORADOR_API_URL}?${parametros}`)).employees;
        } catch (erro) {
            mostrarErro(erro.message);
        }
    }
    if (pedido !== pedidosDeComparativo.colaboradores) return;
    comparativoPorColaborador = dados;
    preencherSelect(
        'employee-filter',
        'Todos os colaboradores',
        dados.employees.map((item) => [item.employee_id, `${item.employee_name} · ${item.employee_id}`]),
    );
    preencherSelect('employee-location', 'Todas as localizações', opcoesDeLocalizacao(dados.employees));
    renderizarComparativoPorColaborador();
}

// Os indicadores vêm do servidor: carregam quando a aba abre e de novo quando
// os dados mudam com ela aberta
const INDICADORES_DAS_ABAS = {
    'ranking-intrajornada': () => carregarRanking('intra'),
    'ranking-interjornada': () => carregarRanking('inter'),
    'ranking-atestados': () => carregarRanking('atestados'),
    'comparativo-ocorrencias': carregarComparativoDeOcorrencias,
    'comparativo-colaborador': carregarComparativoPorColaborador,
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

// Os atestados e as declarações de cada localização, do relatório de afastamentos
function atestadosPorLocalizacao() {
    const contagem = new Map();
    afastamentosDoMes().filter((afastamento) => afastamento.medical).forEach((afastamento) => {
        contagem.set(afastamento.location, (contagem.get(afastamento.location) || 0) + 1);
    });
    return contagem;
}

// A matriz também é a tabela do gráfico de localizações: todo número aparece
// nela. A última coluna são os atestados, que entram no total da localização.
function renderizarMapaDeCalor(localizacoesComOcorrencias) {
    const container = document.getElementById('chart-heatmap');
    const escala = document.getElementById('chart-heatmap-scale');
    const atestados = atestadosPorLocalizacao();
    const localizacoes = [
        ...localizacoesComOcorrencias.map((localizacao) => ({ ...localizacao, atestados: atestados.get(localizacao.nome) || 0 })),
        ...[...atestados.entries()]
            .filter(([nome]) => !localizacoesComOcorrencias.some((localizacao) => localizacao.nome === nome))
            .map(([nome, total]) => ({ nome, total: 0, tipos: {}, atestados: total })),
    ].map((localizacao) => ({ ...localizacao, total: localizacao.total + localizacao.atestados }))
        .sort((a, b) => b.total - a.total || comparar(a.nome, b.nome));
    const presentes = catalogo.types.filter((item) => localizacoes.some((localizacao) => localizacao.tipos[item.code]));
    if (!localizacoes.length) {
        container.innerHTML = vazioDoGrafico();
        escala.innerHTML = '';
        return;
    }

    const maximo = Math.max(...localizacoes.flatMap((localizacao) => [
        localizacao.atestados, ...presentes.map((item) => localizacao.tipos[item.code] || 0),
    ]));
    const vazia = '<td><span class="heat-empty" aria-label="Nenhuma">—</span></td>';
    const linhas = localizacoes.map((localizacao) => {
        const celulas = presentes.map((item) => {
            const valor = localizacao.tipos[item.code] || 0;
            if (!valor) return vazia;
            return `
                <td>
                    <button type="button" class="heat-cell heat-${nivelDeCalor(valor, maximo)}"
                        data-filter-location="${escaparHtml(localizacao.nome)}" data-filter-type="${item.code}"
                        data-tooltip-value="${numero(valor)}" data-tooltip-label="${escaparHtml(`${item.label} · ${localizacao.nome}`)}"
                        aria-label="${escaparHtml(`${localizacao.nome}, ${item.label}: ${valor}`)}">${numero(valor)}</button>
                </td>`;
        }).join('');
        const celulaDeAtestados = !atestados.size ? '' : (localizacao.atestados ? `
                <td>
                    <span class="heat-cell heat-static heat-${nivelDeCalor(localizacao.atestados, maximo)}" tabindex="0"
                        data-tooltip-value="${numero(localizacao.atestados)}" data-tooltip-label="${escaparHtml(`Atestados · ${localizacao.nome}`)}"
                        aria-label="${escaparHtml(`${localizacao.nome}, atestados: ${localizacao.atestados}`)}">${numero(localizacao.atestados)}</span>
                </td>` : vazia);
        return `
            <tr>
                <th scope="row">${escaparHtml(localizacao.nome)}</th>
                ${celulas}${celulaDeAtestados}
                <td class="heat-total">${numero(localizacao.total)}</td>
            </tr>`;
    }).join('');

    container.innerHTML = `
        <table class="heatmap">
            <thead>
                <tr>
                    <th scope="col">Localização</th>
                    ${presentes.map((item) => `<th scope="col">${escaparHtml(item.label)}</th>`).join('')}
                    ${atestados.size ? '<th scope="col">Atestados</th>' : ''}
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
    // Quem rola é o conteúdo ao lado da sidebar, não a janela: a captura pega a rolagem de qualquer elemento
    document.addEventListener('scroll', () => { dica.hidden = true; }, { passive: true, capture: true });
}

// Afastamentos do mês

function afastamentosDoMes() {
    return competencia && competencia.leaves ? competencia.leaves.events : [];
}

// O afastamento sem Data fim segue em aberto
function periodoDoAfastamento([inicio, fim]) {
    if (!fim) return `${dataBr(inicio)} em diante`;
    return inicio === fim ? dataBr(inicio) : `${dataBr(inicio)} a ${dataBr(fim)}`;
}

function datasDoAfastamento(afastamento) {
    return afastamento.periods.map(periodoDoAfastamento).join(', ');
}

const ORDENACOES_DE_AFASTAMENTOS = {
    name: (a, b) => ORDENACOES.name(a, b) || comparar(a.reason, b.reason),
    location: ORDENACOES.location,
    type: (a, b) => comparar(a.reason, b.reason),
    date: (a, b) => a.periods[0][0].localeCompare(b.periods[0][0]),
};

function afastamentosFiltrados() {
    const busca = normalizar(document.getElementById('leaves-search').value);
    const motivo = document.getElementById('leaves-type').value;
    const localizacao = document.getElementById('leaves-location').value;
    return afastamentosDoMes()
        .filter((afastamento) => (!motivo || afastamento.reason === motivo)
            && (!localizacao || afastamento.location === localizacao)
            && (!busca || normalizar([
                afastamento.employee_name, afastamento.employee_id, afastamento.location, afastamento.reason,
                datasDoAfastamento(afastamento),
            ].join(' ')).includes(busca)))
        .sort(ORDENACOES_DE_AFASTAMENTOS[document.getElementById('leaves-sort').value]);
}

function renderizarAfastamentos() {
    const lista = afastamentosFiltrados();
    let mensagem = 'Nenhum afastamento para os filtros selecionados.';
    if (!competencia) mensagem = 'Importe os relatórios para iniciar a conferência.';
    else if (!competencia.leaves) mensagem = 'Relatório de afastamentos não importado nesta competência.';
    else if (!competencia.leaves.events.length) mensagem = 'Nenhum afastamento localizado nesta competência.';
    renderizarTabela({
        id: 'leaves',
        chave: 'afastamentos',
        linhas: lista,
        montarLinha: (afastamento) => `
            <tr>
                <td>${escaparHtml(afastamento.employee_id)}</td>
                <td class="person"><strong>${escaparHtml(afastamento.employee_name)}</strong></td>
                <td>${escaparHtml(afastamento.location)}</td>
                <td>${escaparHtml(afastamento.reason)}</td>
                <td class="evidence">${escaparHtml(datasDoAfastamento(afastamento))}</td>
            </tr>`,
        mensagemVazia: mensagem,
        renderizar: renderizarAfastamentos,
    });
    document.getElementById('leaves-export').disabled = lista.length === 0;
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
                    <td>${escaparHtml(colaborador.location)}</td>
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

// Os afastamentos que cobrem o dia da ocorrência; null é a competência sem o relatório
function renderizarContextoDeAfastamento(afastamentos) {
    const contexto = document.getElementById('leave-context');
    if (afastamentos === null) {
        contexto.innerHTML = '<p>Relatório de afastamentos não importado nesta competência.</p>';
    } else if (!afastamentos.length) {
        contexto.innerHTML = '<p>Nenhum afastamento localizado no relatório importado para esta data.</p>';
    } else {
        contexto.innerHTML = `<ul>${afastamentos.map((afastamento) => `
            <li>
                <strong>${escaparHtml(afastamento.reason)}</strong>
                <span class="muted">· ${periodoDoAfastamento([afastamento.start, afastamento.end])}</span>
            </li>`).join('')}</ul>`;
    }
}

async function carregarHistorico(id) {
    const historico = document.getElementById('treatment-history');
    const contexto = document.getElementById('leave-context');
    historico.innerHTML = '<p class="muted">Carregando...</p>';
    contexto.innerHTML = '<p class="muted">Carregando...</p>';
    try {
        const dados = await requisitar(urlCom(TRATATIVAS_API_URL, id));
        if (!ocorrenciaAberta || ocorrenciaAberta.id !== id) return;
        renderizarContextoDeAfastamento(dados.leaves);
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
        contexto.innerHTML = '';
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
            prioridade(ocorrencia), tipoOcorrencia.actionable ? textoTratativa(ocorrencia) : 'Informativo',
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

function exportarAfastamentos() {
    const competenciaExportada = rotuloPeriodo(periodo.start_date, periodo.end_date);
    const linhas = afastamentosFiltrados().map((afastamento) => [
        competenciaExportada, afastamento.employee_id, afastamento.employee_name, afastamento.location,
        afastamento.reason, datasDoAfastamento(afastamento),
    ]);
    exportarPlanilha(
        'afastamentos',
        'Afastamentos',
        ['Competência', 'Matrícula', 'Colaborador', 'Localização', 'Tipo de afastamento', 'Data(s) do afastamento'],
        linhas,
        [24, 11, 30, 22, 30, 30],
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
    if (atualizarEndereco) {
        history.replaceState(null, '', `#${destino}`);
        // A seção nova abre do começo, como se fosse outra página
        document.querySelector('.main-content').scrollTop = 0;
    }

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
    renderizarAfastamentos();
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
        campo.addEventListener('change', () => (campo.dataset.reportInput === BANCO_DE_HORAS
            ? importarBancoDeHoras(campo)
            : prepararRelatorio(campo)));
    });
    const confirmarImportacao = document.getElementById('confirm-import');
    if (confirmarImportacao) confirmarImportacao.addEventListener('click', processarRelatorios);

    const aoFiltrarOcorrencias = () => {
        paginas.ocorrencias = 1;
        renderizarOcorrencias();
    };
    document.getElementById('occurrence-search').addEventListener('input', aoFiltrarOcorrencias);
    ['filter-employee', 'filter-type', 'filter-location', 'filter-priority', 'filter-treatment', 'occurrence-sort'].forEach((id) => {
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
    document.getElementById('bank-table').addEventListener('click', (evento) => {
        const botao = evento.target.closest('[data-save-bank-note]');
        if (botao) salvarObservacaoDoBanco(botao.parentElement.querySelector('[data-bank-note]'));
    });

    const aoFiltrarAfastamentos = () => {
        paginas.afastamentos = 1;
        renderizarAfastamentos();
    };
    document.getElementById('leaves-search').addEventListener('input', aoFiltrarAfastamentos);
    ['leaves-type', 'leaves-location', 'leaves-sort'].forEach((id) => {
        document.getElementById(id).addEventListener('change', aoFiltrarAfastamentos);
    });
    document.getElementById('leaves-export').addEventListener('click', exportarAfastamentos);

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
            const campo = document.getElementById(id);
            if (campo) campo.addEventListener('change', aoFiltrarRanking);
        });
    });

    // Os totais de todas as competências já estão carregados: marcar outra
    // competência ou escolher o indicador só redesenha os gráficos
    document.getElementById('sector-indicator').addEventListener('change', renderizarEvolucao);
    document.addEventListener('change', (evento) => {
        const caixa = evento.target.closest('[data-compare-check]');
        if (!caixa) return;
        const chave = caixa.dataset.compareCheck;
        if (caixa.checked) competenciasMarcadas[chave].add(caixa.value);
        else competenciasMarcadas[chave].delete(caixa.value);
        if (chave === 'ocorrencias') renderizarEvolucao();
        else carregarComparativoPorColaborador();
    });
    document.getElementById('employee-indicator').addEventListener('change', carregarComparativoPorColaborador);
    ['employee-filter', 'employee-location'].forEach((id) => {
        document.getElementById(id).addEventListener('change', () => {
            paginas.comparaColaboradores = 1;
            renderizarComparativoPorColaborador();
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
