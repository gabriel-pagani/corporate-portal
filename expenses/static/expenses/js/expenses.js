// Despesas: a lista, o envio das fotos da nota, a conferência, a validação e o
// histórico de cada despesa. Cada tela tem a sua rota (/expenses/add/,
// /expenses/12/): o voltar do celular volta para a tela anterior.

(() => {
    const content = document.getElementById('content');
    const csrfToken = content.dataset.csrfToken;
    const readJson = (id) => JSON.parse(document.getElementById(id).textContent);

    const access = readJson('expenses-access');
    const types = readJson('expenses-types');
    const limits = readJson('expenses-limits');
    const statuses = readJson('expenses-statuses');
    const reviewer = access.control || access.finance;
    const accepted = limits.accepted.split(',');

    const urlFor = (name, id) => content.dataset[name].replace('/0/', `/${id}/`);
    const detailPattern = new RegExp(`^${content.dataset.detailUrl.replace('/0/', '/(\\d+)/')}$`);

    const state = {
        scope: reviewer ? 'queue' : 'mine',
        page: 1,
        expense: null,
        items: [],
        // A mensagem que aparece depois da troca de tela (a troca limpa as mensagens)
        flash: null,
    };

    // ---------- Utilitários ----------

    const moneyFormat = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });

    function toCents(text) {
        let value = String(text ?? '').trim().replace(/\s|R\$/g, '');
        if (!value) return null;
        // 1.234,56 e 1234,56 viram 1234.56; 1234.56 fica como está
        if (value.includes(',')) value = value.replace(/\./g, '').replace(',', '.');
        const number = Number(value);
        return Number.isFinite(number) ? Math.round(number * 100) : NaN;
    }

    function toApiDecimal(text) {
        let value = String(text ?? '').trim().replace(/\s|R\$/g, '');
        if (value.includes(',')) value = value.replace(/\./g, '').replace(',', '.');
        return value;
    }

    const formatMoney = (cents) => moneyFormat.format((cents || 0) / 100);
    const toInputDecimal = (value) => (value === '' || value === null || value === undefined) ? '' : String(value).replace('.', ',');

    function formatQuantity(value) {
        const number = Number(value);
        return Number.isFinite(number) ? String(Number(number.toFixed(3))).replace('.', ',') : String(value);
    }

    function element(tag, attributes = {}, children = []) {
        const node = document.createElement(tag);
        for (const [name, value] of Object.entries(attributes)) {
            if (value === null || value === undefined || value === false) continue;
            if (name === 'text') node.textContent = value;
            else if (name === 'className') node.className = value;
            else if (name.startsWith('on')) node.addEventListener(name.slice(2), value);
            else node.setAttribute(name, value === true ? '' : value);
        }
        for (const child of [].concat(children)) {
            if (child === null || child === undefined || child === false) continue;
            node.append(child instanceof Node ? child : document.createTextNode(String(child)));
        }
        return node;
    }

    const icon = (name) => element('i', { className: `fas ${name}`, 'aria-hidden': 'true' });

    async function api(url, options = {}) {
        let response;
        try {
            response = await fetch(url, {
                credentials: 'same-origin',
                ...options,
                headers: { 'X-CSRFToken': csrfToken, ...(options.headers || {}) },
            });
        } catch {
            throw Object.assign(new Error('Sem conexão com o portal. Confira a internet e tente de novo.'), { status: 0 });
        }
        let data = {};
        try {
            data = await response.json();
        } catch {
            data = {};
        }
        if (!response.ok) {
            const message = data.detail || (response.status === 413
                ? 'As fotos passam do tamanho aceito. Envie fotos menores.'
                : 'Não foi possível concluir. Tente de novo.');
            throw Object.assign(new Error(message), { status: response.status, data });
        }
        return data;
    }

    const postJson = (url, payload) => api(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });

    const alertBox = document.getElementById('alert-error');
    const rereadButton = document.getElementById('reread-button');
    const successBox = document.getElementById('success-message');

    // A resposta do sistema aparece no canto: o sucesso some sozinho, o erro fica até ser fechado
    const SUCCESS_SECONDS = 5;
    let successTimer = null;

    function showError(message) {
        clearTimeout(successTimer);
        document.getElementById('alert-error-text').textContent = message;
        alertBox.hidden = false;
        successBox.hidden = true;
    }

    function showSuccess(message) {
        clearTimeout(successTimer);
        document.getElementById('success-message-text').textContent = message;
        successBox.hidden = false;
        alertBox.hidden = true;
        successTimer = setTimeout(() => { successBox.hidden = true; }, SUCCESS_SECONDS * 1000);
    }

    function clearMessages() {
        clearTimeout(successTimer);
        alertBox.hidden = true;
        successBox.hidden = true;
    }

    document.getElementById('alert-error-close').addEventListener('click', () => { alertBox.hidden = true; });
    successBox.addEventListener('click', () => { successBox.hidden = true; });

    function statusBadge(status, label, title) {
        return element('span', { className: `status-badge status-${status}`, text: label, title });
    }

    // Na lista do funcionário, que é vista no celular, a situação vai abreviada para
    // caber ao lado do título e do valor; o nome inteiro fica na dica do selo
    const shortStatus = { C: 'Ag. conferência', S: 'Ag. correção', E: 'Ag. explicação', V: 'Ag. validação' };

    // ---------- Telas ----------

    const views = ['list-view', 'submit-view', 'detail-view'];

    function showView(id) {
        for (const view of views) {
            const node = document.getElementById(view);
            if (node) node.hidden = view !== id;
        }
        // O CSS mostra o Enviar nota do rodapé só na lista
        content.dataset.view = id;
        window.scrollTo(0, 0);
    }

    function route() {
        const path = window.location.pathname;
        const match = path.match(detailPattern);
        if (match) {
            loadDetail(Number(match[1]));
        } else if (path === content.dataset.addUrl && access.employee) {
            showView('submit-view');
        } else {
            showView('list-view');
            loadList();
            // A mensagem de quem chegou à lista vindo de outra tela, como depois da exclusão
            if (state.flash) showSuccess(state.flash);
            state.flash = null;
        }
    }

    function navigate(url) {
        if (url !== window.location.pathname) history.pushState(null, '', url);
        clearMessages();
        route();
    }

    window.addEventListener('popstate', () => {
        clearMessages();
        route();
    });

    // Os links entre as telas trocam a rota sem recarregar a página; com Ctrl ou
    // o botão do meio, abrem numa aba nova como qualquer link
    document.addEventListener('click', (event) => {
        const link = event.target.closest('a[data-route]');
        if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        navigate(link.getAttribute('href'));
    });

    // ---------- Lista ----------

    const statusFilter = document.getElementById('status-filter');
    if (statusFilter) {
        for (const status of statuses) {
            statusFilter.append(element('option', { value: status.value, text: status.label }));
        }
    }

    const searchInput = document.getElementById('search-input');
    let searchTimer;

    // Os filtros do funcionário. "Em andamento" junta o que está na conferência e na validação.
    const chipFilters = [
        { label: 'Todas', value: '' },
        { label: 'Aguardando correção', value: 'S', attention: true },
        { label: 'Em andamento', value: 'C,E,V' },
        { label: 'Aprovadas', value: 'A' },
        { label: 'Rejeitadas', value: 'R' },
    ];
    const chipsBox = document.getElementById('status-chips');
    state.chip = '';
    state.counts = {};

    function renderChips() {
        if (!chipsBox) return;
        const counts = state.counts;
        chipsBox.replaceChildren(...chipFilters.map((chip) => {
            const values = chip.value ? chip.value.split(',') : Object.keys(counts);
            const total = values.reduce((sum, value) => sum + (counts[value] || 0), 0);
            const active = state.chip === chip.value;
            return element('button', {
                type: 'button',
                className: `chip${active ? ' active' : ''}${chip.attention && total ? ' attention' : ''}`,
                'aria-pressed': active ? 'true' : 'false',
                onclick: () => {
                    state.chip = chip.value;
                    renderChips();
                    loadList();
                },
            }, [chip.label, element('span', { className: 'chip-count', text: String(total) })]);
        }));
    }

    function listUrl(page) {
        const params = new URLSearchParams({ scope: state.scope, page });
        const status = statusFilter ? statusFilter.value : state.chip;
        if (status) params.set('status', status);
        if (searchInput && searchInput.value.trim()) params.set('q', searchInput.value.trim());
        return `${content.dataset.listUrl}?${params}`;
    }

    function expenseRow(expense) {
        // A nota que espera o funcionário fica em destaque na lista dele
        const needsAction = !reviewer && expense.status === 'S';
        // O funcionário vê só a data de envio; quem confere vê também quem enviou e o centro de custo
        const meta = reviewer ? [
            expense.employee,
            expense.cost_center,
            `Enviada em ${expense.created_at}`,
        ].filter(Boolean).join(' · ') : `Enviada em ${expense.created_at}`;
        return element('a', { className: `expense-row${needsAction ? ' needs-action' : ''}`, href: urlFor('detailUrl', expense.id), 'data-route': '' }, [
            element('span', { className: 'row-title' }, [
                `Despesa #${expense.id}`,
                reviewer || !shortStatus[expense.status]
                    ? statusBadge(expense.status, expense.status_display)
                    : statusBadge(expense.status, shortStatus[expense.status], expense.status_display),
                expense.ai_unread ? element('span', { className: 'ai-unread-badge' }, [
                    icon('fa-robot'), ' IA não leu',
                ]) : null,
                expense.alerts_count ? element('span', { className: 'alert-count' }, [
                    icon('fa-triangle-exclamation'), ` ${expense.alerts_count} alerta${expense.alerts_count > 1 ? 's' : ''}`,
                ]) : null,
            ]),
            element('span', { className: 'row-meta', text: meta }),
            // Para o funcionário o valor em destaque é o que ele vai receber, não o total da nota
            element('span', { className: 'row-values' }, reviewer ? [
                element('strong', { text: expense.reimbursed_total }),
                expense.total ? `de ${expense.total}` : 'reembolsado',
            ] : [
                element('strong', { text: expense.reimbursed_total }),
                element('span', { className: 'row-label', text: 'valor a reembolsar' }),
            ]),
            needsAction ? element('span', { className: 'row-action' }, [icon('fa-camera'), ' Toque para enviar novas fotos']) : null,
        ]);
    }

    async function loadList(page = 1) {
        state.page = page;
        const list = document.getElementById('expense-list');
        try {
            const data = await api(listUrl(page));
            if (page === 1) list.replaceChildren();
            list.append(...data.expenses.map(expenseRow));
            document.getElementById('list-empty').hidden = list.children.length > 0;
            document.getElementById('list-more').hidden = !data.has_next;
            const counter = document.getElementById('queue-count');
            if (counter) counter.textContent = data.queue_count ? String(data.queue_count) : '';
            if (data.counts) {
                state.counts = data.counts;
                renderChips();
            }
        } catch (error) {
            showError(error.message);
        }
    }

    document.getElementById('list-more').addEventListener('click', () => loadList(state.page + 1));
    if (statusFilter) statusFilter.addEventListener('change', () => loadList());
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => loadList(), 300);
        });
    }
    renderChips();

    const tabs = document.querySelectorAll('.tab[data-scope]');
    function selectTab(scope) {
        state.scope = scope;
        tabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.scope === scope));
    }
    tabs.forEach((tab) => tab.addEventListener('click', () => {
        selectTab(tab.dataset.scope);
        loadList();
    }));
    if (reviewer) selectTab('queue');

    // ---------- Fotos ----------

    // A foto do celular passa fácil de 10 MB, e três delas demoram a subir no 4G.
    // Ela é reduzida aqui ao tamanho que o servidor guarda (lado maior de 3000 px):
    // a nota chega igual, só mais rápido.
    const SHRINK_SIDE = 3000;
    const SHRINK_QUALITY = 0.9;
    const SMALL_FILE = 1.5 * 1024 * 1024;

    async function shrink(file) {
        if (file.type && !accepted.includes(file.type)) return file;
        const url = URL.createObjectURL(file);
        try {
            const image = new Image();
            image.src = url;
            await image.decode();
            // O navegador já aplica a rotação do EXIF no tamanho e no desenho da imagem
            const scale = Math.min(1, SHRINK_SIDE / Math.max(image.naturalWidth, image.naturalHeight));
            if (scale === 1 && file.size < SMALL_FILE) return file;
            const canvas = document.createElement('canvas');
            canvas.width = Math.round(image.naturalWidth * scale);
            canvas.height = Math.round(image.naturalHeight * scale);
            const context = canvas.getContext('2d');
            // O fundo transparente do PNG viraria preto no JPEG
            context.fillStyle = '#fff';
            context.fillRect(0, 0, canvas.width, canvas.height);
            context.drawImage(image, 0, 0, canvas.width, canvas.height);
            const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', SHRINK_QUALITY));
            if (!blob || blob.size >= file.size) return file;
            const name = `${(file.name || 'foto').replace(/\.[^.]+$/, '')}.jpg`;
            return new File([blob], name, { type: 'image/jpeg' });
        } catch {
            // Sem memória ou formato que o navegador não abre: vai o original, e o servidor confere
            return file;
        } finally {
            URL.revokeObjectURL(url);
        }
    }

    function photoPicker(prefix, onChange) {
        const files = [];
        const urls = [];
        const previews = document.getElementById(`${prefix}-previews`);
        const count = document.getElementById(`${prefix}-count`);
        const actions = document.getElementById(`${prefix}-actions`);
        const megabytes = Math.round(limits.max_size / (1024 * 1024));
        let preparing = 0;

        function render() {
            previews.replaceChildren(
                ...files.map((file, index) => element('figure', {}, [
                    element('img', { src: urls[index], alt: `Foto ${index + 1}` }),
                    element('span', { className: 'photo-number', text: String(index + 1) }),
                    element('button', {
                        type: 'button',
                        className: 'photo-remove',
                        title: 'Remover a foto',
                        'aria-label': `Remover a foto ${index + 1}`,
                        onclick: () => {
                            URL.revokeObjectURL(urls[index]);
                            files.splice(index, 1);
                            urls.splice(index, 1);
                            render();
                        },
                    }, [icon('fa-xmark')]),
                ])),
                ...Array.from({ length: preparing }, () => element('figure', { className: 'preparing' }, [
                    icon('fa-spinner fa-spin'), element('span', { text: 'Preparando...' }),
                ])),
            );
            count.hidden = files.length + preparing === 0;
            count.textContent = `${files.length} de ${limits.max_photos} foto${limits.max_photos > 1 ? 's' : ''}`;
            // Com o limite atingido, os botões de foto saem da frente
            actions.hidden = files.length + preparing >= limits.max_photos;
            onChange(files.length, preparing > 0);
        }

        async function add(list) {
            clearMessages();
            const room = limits.max_photos - files.length - preparing;
            let chosen = Array.from(list);
            if (chosen.length > room) {
                showError(`Envie no máximo ${limits.max_photos} fotos por nota.`);
                chosen = chosen.slice(0, Math.max(room, 0));
            }
            // Alguns celulares não dizem o tipo: aí o servidor confere
            const valid = chosen.filter((file) => !file.type || accepted.includes(file.type));
            if (valid.length < chosen.length) showError('Envie apenas fotos nos formatos JPEG, PNG ou WEBP.');

            preparing += valid.length;
            render();
            for (const original of valid) {
                const file = await shrink(original);
                preparing -= 1;
                if (file.size > limits.max_size) {
                    showError(`Cada foto pode ter até ${megabytes} MB.`);
                } else {
                    files.push(file);
                    urls.push(URL.createObjectURL(file));
                }
                render();
            }
        }

        for (const source of ['camera', 'gallery']) {
            const input = document.getElementById(`${prefix}-${source}`);
            input.addEventListener('change', () => {
                add(input.files);
                input.value = '';
            });
        }

        return {
            files: () => files.slice(),
            clear() {
                urls.forEach((url) => URL.revokeObjectURL(url));
                files.length = 0;
                urls.length = 0;
                render();
            },
        };
    }

    function photosForm(files, note) {
        const form = new FormData();
        files.forEach((file, index) => form.append('photos', file, file.name || `foto-${index + 1}.jpg`));
        form.append('note', note);
        return form;
    }

    // O envio das fotos mostra o quanto já subiu: no 4G ele leva um tempo, e
    // depois vem a análise da IA. O fetch não conta o upload; o XMLHttpRequest conta.
    let uploading = false;

    window.addEventListener('beforeunload', (event) => {
        if (!uploading) return;
        event.preventDefault();
        event.returnValue = '';
    });

    function progressView(prefix, readingText) {
        const box = document.getElementById(`${prefix}-progress`);
        const bar = document.getElementById(`${prefix}-progress-bar`);
        const text = document.getElementById(`${prefix}-progress-text`);
        return {
            sending(fraction) {
                const percent = Math.round(fraction * 100);
                box.hidden = false;
                box.classList.remove('reading');
                bar.style.width = `${percent}%`;
                text.textContent = `Enviando as fotos... ${percent}%`;
            },
            reading() {
                box.hidden = false;
                box.classList.add('reading');
                bar.style.width = '100%';
                text.textContent = readingText;
            },
            hide() {
                box.hidden = true;
                box.classList.remove('reading');
                bar.style.width = '0';
            },
        };
    }

    function upload(url, form, progress) {
        return new Promise((resolve, reject) => {
            const request = new XMLHttpRequest();
            request.open('POST', url);
            request.setRequestHeader('X-CSRFToken', csrfToken);
            request.responseType = 'json';
            request.upload.addEventListener('progress', (event) => {
                if (event.lengthComputable) progress.sending(event.loaded / event.total);
            });
            request.upload.addEventListener('load', () => progress.reading());
            request.addEventListener('load', () => {
                const data = request.response || {};
                if (request.status >= 200 && request.status < 300) {
                    resolve(data);
                    return;
                }
                const message = data.detail || (request.status === 413
                    ? 'As fotos passam do tamanho aceito. Envie fotos menores.'
                    : 'Não foi possível concluir. Tente de novo.');
                reject(Object.assign(new Error(message), { status: request.status, data }));
            });
            request.addEventListener('error', () => reject(Object.assign(
                new Error('Sem conexão com o portal. Confira a internet e tente de novo.'), { status: 0 },
            )));
            request.send(form);
        });
    }

    // ---------- Envio ----------

    if (access.employee) {
        const sendButton = document.getElementById('submit-send');
        const submitNote = document.getElementById('submit-note');
        const progress = progressView('submit', 'Fotos enviadas. Analisando a nota... isso pode levar até um minuto.');
        const picker = photoPicker('submit', (count, busy) => {
            sendButton.disabled = count === 0 || busy || uploading;
        });

        sendButton.addEventListener('click', async () => {
            clearMessages();
            sendButton.disabled = true;
            uploading = true;
            progress.sending(0);
            try {
                const data = await upload(content.dataset.listUrl, photosForm(picker.files(), submitNote.value), progress);
                picker.clear();
                submitNote.value = '';
                state.flash = 'Nota enviada. A despesa agora aguarda a conferência.';
                navigate(urlFor('detailUrl', data.expense.id));
            } catch (error) {
                showError(error.message);
            } finally {
                uploading = false;
                progress.hide();
                sendButton.disabled = picker.files().length === 0;
            }
        });
    }

    // ---------- A nota ----------

    const form = document.getElementById('expense-form');
    const fieldInputs = {
        number: document.getElementById('field-number'),
        issue_date: document.getElementById('field-issue-date'),
        cnpj: document.getElementById('field-cnpj'),
        total: document.getElementById('field-total'),
        expense_type: document.getElementById('field-type'),
        access_key: document.getElementById('field-access-key'),
    };
    const typeSelect = fieldInputs.expense_type;
    for (const type of types) typeSelect.append(element('option', { value: type.id, text: type.name }));

    const requiredToApprove = [
        ['number', 'número da nota'],
        ['issue_date', 'data'],
        ['total', 'valor total'],
        ['cnpj', 'CNPJ do emitente'],
        ['expense_type', 'tipo'],
    ];

    function canEdit() {
        return Boolean(state.expense && state.expense.can.edit);
    }

    function itemRow(item, index) {
        const editable = canEdit();
        const update = (name) => (event) => {
            item[name] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
            if (name === 'non_reimbursable') row.classList.toggle('non-reimbursable', item.non_reimbursable);
            refreshTotals();
        };
        const row = element('tr', { className: item.non_reimbursable ? 'non-reimbursable' : '' }, [
            element('td', {}, [
                element('input', {
                    type: 'text', value: item.description, maxlength: 200, disabled: !editable,
                    'aria-label': `Descrição do item ${index + 1}`, oninput: update('description'),
                }),
                item.ai_group ? element('span', { className: 'ai-group', text: `IA: ${item.ai_group}` }) : null,
            ]),
            element('td', {}, [element('input', {
                type: 'text', className: 'item-quantity', inputmode: 'decimal', value: item.quantity,
                disabled: !editable, 'aria-label': `Quantidade do item ${index + 1}`, oninput: update('quantity'),
            })]),
            element('td', {}, [element('input', {
                type: 'text', className: 'item-amount', inputmode: 'decimal', value: item.amount,
                disabled: !editable, 'aria-label': `Valor do item ${index + 1}`, oninput: update('amount'),
            })]),
            element('td', { className: 'item-check' }, [element('input', {
                type: 'checkbox', checked: item.non_reimbursable, disabled: !editable,
                'aria-label': `Item ${index + 1} não reembolsável`, onchange: update('non_reimbursable'),
            })]),
            element('td', {}, editable ? [element('button', {
                type: 'button', className: 'button small danger', title: 'Remover o item',
                'aria-label': `Remover o item ${index + 1}`,
                onclick: () => {
                    state.items.splice(index, 1);
                    renderItems();
                },
            }, [icon('fa-trash')])] : []),
        ]);
        return row;
    }

    function renderItems() {
        document.getElementById('items-body').replaceChildren(...state.items.map(itemRow));
        document.getElementById('items-empty').hidden = state.items.length > 0;
        refreshTotals();
    }

    function totals() {
        let all = 0;
        let reimbursed = 0;
        for (const item of state.items) {
            const cents = toCents(item.amount);
            if (!Number.isFinite(cents)) continue;
            all += cents;
            if (!item.non_reimbursable) reimbursed += cents;
        }
        return { all, reimbursed };
    }

    function missingToApprove() {
        const missing = requiredToApprove
            .filter(([name]) => !fieldInputs[name].value.trim())
            .map(([, label]) => label);
        return missing;
    }

    function refreshTotals() {
        const { all, reimbursed } = totals();
        document.getElementById('items-total').textContent = formatMoney(all);
        document.getElementById('reimbursed-total').textContent = formatMoney(reimbursed);
        refreshApproveHint();
    }

    function refreshApproveHint() {
        const hint = document.getElementById('approve-hint');
        const approve = document.getElementById('approve-button');
        if (!state.expense || !state.expense.can.act) return;
        const problems = [];
        if (canEdit()) {
            const missing = missingToApprove();
            if (missing.length) problems.push(`preencha: ${missing.join(', ')}`);
            if (totals().reimbursed <= 0) problems.push('o valor reembolsado precisa ser maior que zero');
        }
        approve.disabled = problems.length > 0;
        hint.hidden = problems.length === 0;
        hint.textContent = problems.length ? `Para aprovar, ${problems.join('; ')}.` : '';
    }

    Object.values(fieldInputs).forEach((input) => input.addEventListener('input', () => {
        input.classList.remove('invalid');
        refreshApproveHint();
    }));

    document.getElementById('add-item').addEventListener('click', () => {
        state.items.push({ id: null, description: '', quantity: '1', amount: '', non_reimbursable: false, ai_group: '' });
        renderItems();
        const inputs = document.querySelectorAll('#items-body tr:last-child input[type="text"]');
        if (inputs.length) inputs[0].focus();
    });

    function formData() {
        return {
            number: fieldInputs.number.value.trim(),
            issue_date: fieldInputs.issue_date.value,
            cnpj: fieldInputs.cnpj.value.trim(),
            total: toApiDecimal(fieldInputs.total.value),
            expense_type: fieldInputs.expense_type.value,
            access_key: fieldInputs.access_key.value.trim(),
            items: state.items.map((item) => ({
                id: item.id,
                description: item.description.trim(),
                quantity: toApiDecimal(item.quantity),
                amount: toApiDecimal(item.amount),
                non_reimbursable: item.non_reimbursable,
            })),
        };
    }

    function attentionRow(iconName, meta, text, { danger = false, extra = null } = {}) {
        return element('li', { className: danger ? 'danger' : '' }, [
            icon(iconName),
            element('div', { className: 'attention-body' }, [
                meta ? element('span', { className: 'attention-meta', text: meta }) : null,
                text ? element('p', { className: 'attention-text', text }) : null,
                extra,
            ]),
        ]);
    }

    // Quem confere e quem valida veem num quadro só o que pede atenção: primeiro o que
    // fazer (a observação da última etapa), depois o que conferir (a IA)
    function renderAttention(expense) {
        const rows = [];
        const last = expense.timeline[expense.timeline.length - 1];
        // A observação do envio já aparece em "Dados da despesa": aqui só a das etapas seguintes
        if (expense.timeline.length > 1 && last.note && expense.status !== 'A') {
            rows.push(attentionRow(
                'fa-comment', `${last.action_display} · ${last.author_name}, ${last.created_at}`, last.note,
                { danger: expense.status === 'R' },
            ));
        }
        rereadButton.hidden = !expense.can.reread;
        if (expense.ai_status !== 'ok') {
            rows.push(attentionRow('fa-robot', 'A IA não leu esta nota', expense.can.reread
                ? 'A análise não aconteceu no envio. Peça a leitura de novo ou preencha os dados a partir das fotos.'
                : 'A análise não aconteceu no envio: os dados foram preenchidos a partir das fotos.',
            { danger: true, extra: expense.can.reread ? rereadButton : null }));
        }
        for (const alert of expense.alerts || []) rows.push(attentionRow('fa-robot', 'Alerta da IA', alert));

        const box = document.getElementById('attention');
        // O botão volta para o quadro antes de a lista ser trocada, para não sair da página
        if (!expense.can.reread) box.append(rereadButton);
        document.getElementById('attention-list').replaceChildren(...rows);
        box.hidden = rows.length === 0;
    }

    // O que o funcionário vê no topo da nota: o que está acontecendo e o que ele precisa fazer
    const banners = {
        C: {
            icon: 'fa-magnifying-glass', title: 'Em conferência',
            text: () => 'A sua despesa está sendo conferida. Você recebe um e-mail quando a situação mudar.',
        },
        S: {
            icon: 'fa-camera', title: 'Envie novas fotos', tone: 'attention',
            text: (expense) => (expense.last_note
                ? `Foi pedida uma correção: ${expense.last_note}`
                : 'Foi pedida uma correção na despesa.'),
        },
        E: {
            icon: 'fa-hourglass-half', title: 'Em análise',
            text: () => 'A despesa está sendo analisada. Você não precisa fazer nada.',
        },
        V: {
            icon: 'fa-hourglass-half', title: 'Em validação',
            text: () => 'A despesa foi conferida e agora aguarda a validação.',
        },
        A: {
            icon: 'fa-circle-check', title: 'Aprovada', tone: 'success',
            text: (expense) => `Valor reembolsado: ${expense.reimbursed_total}.`,
        },
        R: {
            icon: 'fa-circle-xmark', title: 'Rejeitada', tone: 'danger',
            text: (expense) => (expense.last_note ? `Motivo: ${expense.last_note}` : 'A despesa foi rejeitada e está encerrada.'),
        },
    };

    function renderStatusBanner(expense) {
        const banner = document.getElementById('status-banner');
        const config = banners[expense.status];
        banner.hidden = !config;
        if (!config) return;
        banner.className = `status-banner${config.tone ? ` ${config.tone}` : ''}`;
        document.getElementById('status-banner-icon').className = `fas ${config.icon}`;
        document.getElementById('status-banner-title').textContent = config.title;
        document.getElementById('status-banner-text').textContent = config.text(expense);
    }

    function renderEmployeeSummary(expense) {
        const fields = expense.fields;
        const rows = [];
        if (expense.status !== 'R') {
            rows.push([expense.status === 'A' ? 'Valor reembolsado' : 'Valor a reembolsar (previsto)', expense.reimbursed_total, 'highlight']);
        }
        rows.push(
            ['Tipo', expense.expense_type || '-'],
            ['Número', fields.number || '-'],
            ['Data', expense.issue_date || '-'],
            ['Emitente', fields.cnpj_display || '-'],
            ['Enviada em', expense.created_at],
            ['Sua observação', expense.employee_note || 'Sem observação.'],
        );
        document.getElementById('summary-list').replaceChildren(...rows.map(([label, value, tone]) => element('div', {
            className: `summary-row${tone ? ` ${tone}` : ''}`,
        }, [element('dt', { text: label }), element('dd', { text: value })])));

        const items = expense.items.map((item) => element('li', { className: item.non_reimbursable ? 'non-reimbursable' : '' }, [
            element('span', { className: 'item-name' }, [
                item.description,
                item.non_reimbursable ? element('small', { className: 'item-tag', text: 'Não reembolsável' }) : null,
            ]),
            element('span', { className: 'item-value' }, [
                formatMoney(toCents(item.amount)),
                Number(item.quantity) !== 1 ? element('small', { text: `Qtd. ${formatQuantity(item.quantity)}` }) : null,
            ]),
        ]));
        document.getElementById('summary-items').replaceChildren(
            ...(items.length ? items : [element('li', { className: 'muted', text: 'Os itens ainda não foram preenchidos.' })]),
        );
    }

    function renderPhotos(expense) {
        document.getElementById('detail-photos').replaceChildren(...expense.photos.map((photo, index) => element('a', {
            href: photo.url, target: '_blank', rel: 'noopener', title: 'Abrir a foto em tamanho real',
        }, [
            element('img', { src: photo.url, alt: `Foto ${index + 1} da nota`, loading: 'lazy' }),
            element('span', { className: 'photo-caption', text: `Foto ${index + 1} · toque para ampliar` }),
        ])));
    }

    function renderMeta(expense) {
        const rows = reviewer ? [
            ['Funcionário', `${expense.employee} (${expense.employee_username})`],
            ['Centro de custo', expense.cost_center || '-'],
            ['Enviada em', expense.created_at],
        ] : [['Enviada em', expense.created_at]];
        document.getElementById('detail-meta').replaceChildren(...rows.flatMap(([label, value]) => [
            element('dt', { text: label }), element('dd', { text: value }),
        ]));
        document.getElementById('detail-employee-note').textContent = expense.employee_note || 'Sem observação.';
    }

    function renderFields(expense) {
        const editable = canEdit();
        const fields = expense.fields;
        fieldInputs.number.value = fields.number;
        fieldInputs.issue_date.value = fields.issue_date;
        fieldInputs.cnpj.value = fields.cnpj_display;
        fieldInputs.total.value = toInputDecimal(fields.total);
        fieldInputs.access_key.value = fields.access_key;
        if (fields.expense_type_id && !typeSelect.querySelector(`option[value="${fields.expense_type_id}"]`)) {
            typeSelect.append(element('option', { value: fields.expense_type_id, text: expense.expense_type }));
        }
        typeSelect.value = fields.expense_type_id || '';
        Object.values(fieldInputs).forEach((input) => {
            input.disabled = !editable;
            input.classList.remove('invalid');
        });
        document.getElementById('add-item').hidden = !editable;
        state.items = expense.items.map((item) => ({
            ...item,
            quantity: formatQuantity(item.quantity),
            amount: toInputDecimal(item.amount),
        }));
        renderItems();
    }

    function renderActions(expense) {
        const actions = document.getElementById('detail-actions');
        actions.hidden = !expense.can.act;
        if (!expense.can.act) return;
        const control = expense.status === 'C' || expense.status === 'E';
        document.getElementById('correction-button').textContent = control
            ? 'Pedir correção ao funcionário' : 'Devolver para a conferência';
        document.getElementById('approve-button').textContent = !control
            ? 'Aprovar' : (expense.explanation_required ? 'Explicar e aprovar' : 'Aprovar e enviar para a validação');
        refreshApproveHint();
    }

    function renderTimeline(expense) {
        const list = document.getElementById('timeline');
        list.replaceChildren(...expense.timeline.map((event) => element('li', {}, [
            element('div', { className: 'event-title', text: event.action_display }),
            element('div', {
                className: 'event-meta',
                // O funcionário não recebe o nome de quem conferiu ou validou
                text: [event.created_at, event.author_name].filter(Boolean).join(' · '),
            }),
            event.note ? element('p', { className: 'event-note', text: event.note }) : null,
        ])));
    }

    function renderResubmit(expense) {
        const box = document.getElementById('resubmit-box');
        box.hidden = !expense.can.resubmit;
    }

    function renderDiscard(expense) {
        const box = document.getElementById('discard-box');
        if (box) box.hidden = !expense.can.discard;
    }

    function renderDetail(expense) {
        state.expense = expense;
        document.getElementById('detail-title').textContent = `Despesa #${expense.id}`;
        const badge = document.getElementById('detail-status');
        badge.className = `status-badge status-${expense.status}`;
        badge.textContent = expense.status_display;
        // O funcionário já tem o aviso da situação logo abaixo: o título fica só com a nota, no centro
        badge.hidden = !reviewer;
        // O funcionário vê a nota em texto, com o aviso da situação; quem confere vê o formulário
        const employeeView = !reviewer;
        document.getElementById('expense-form').hidden = employeeView;
        document.getElementById('detail-meta-card').hidden = employeeView;
        document.getElementById('employee-summary').hidden = !employeeView;
        document.querySelector('.detail-photos').classList.toggle('compact', employeeView);
        if (employeeView) {
            document.getElementById('attention').hidden = true;
            renderStatusBanner(expense);
            renderEmployeeSummary(expense);
        } else {
            document.getElementById('status-banner').hidden = true;
            renderAttention(expense);
            renderMeta(expense);
            renderFields(expense);
        }
        renderPhotos(expense);
        renderActions(expense);
        renderTimeline(expense);
        renderResubmit(expense);
        renderDiscard(expense);
    }

    async function loadDetail(id) {
        try {
            const data = await api(urlFor('expenseUrl', id));
            showView('detail-view');
            renderDetail(data.expense);
            if (state.flash) showSuccess(state.flash);
        } catch (error) {
            showView('list-view');
            loadList();
            showError(error.message);
        } finally {
            state.flash = null;
        }
    }

    function markInvalid(errors) {
        for (const name of Object.keys(errors || {})) {
            if (fieldInputs[name]) fieldInputs[name].classList.add('invalid');
        }
    }

    // ---------- Ações ----------

    const noteDialog = document.getElementById('note-dialog');
    const noteInput = document.getElementById('note-input');
    const noteError = document.getElementById('note-error');

    function askNote({ title, text, label, button, required, danger, withNote = true }) {
        document.getElementById('note-title').textContent = title;
        document.getElementById('note-text').textContent = text;
        document.getElementById('note-label').textContent = label || '';
        // Só a confirmação, sem observação: o campo some
        noteInput.closest('.field').hidden = !withNote;
        const confirmButton = document.getElementById('note-confirm');
        confirmButton.textContent = button;
        confirmButton.classList.toggle('danger', Boolean(danger));
        noteInput.value = '';
        noteError.hidden = true;

        return new Promise((resolve) => {
            const finish = (value) => {
                noteDialog.close();
                document.getElementById('note-form').onsubmit = null;
                document.getElementById('note-cancel').onclick = null;
                noteDialog.oncancel = null;
                resolve(value);
            };
            document.getElementById('note-form').onsubmit = (event) => {
                event.preventDefault();
                const note = noteInput.value.trim();
                if (required && !note) {
                    noteError.textContent = 'A observação é obrigatória.';
                    noteError.hidden = false;
                    noteInput.focus();
                    return;
                }
                finish(note);
            };
            document.getElementById('note-cancel').onclick = () => finish(null);
            noteDialog.oncancel = (event) => {
                event.preventDefault();
                finish(null);
            };
            noteDialog.showModal();
            if (withNote) noteInput.focus();
        });
    }

    function actionDialog(action, expense) {
        const control = expense.status === 'C' || expense.status === 'E';
        if (action === 'reject') {
            return {
                title: `Rejeitar a despesa #${expense.id}?`,
                text: 'A despesa fica encerrada de vez, sem reenvio. O funcionário recebe o motivo por e-mail.',
                label: 'Motivo da rejeição (obrigatório)',
                button: 'Rejeitar',
                required: true,
                danger: true,
            };
        }
        if (action === 'request_correction') {
            return control ? {
                title: 'Pedir correção ao funcionário?',
                text: 'A despesa volta ao funcionário para ele enviar novas fotos. Os dados que você editou ficam guardados.',
                label: 'O que o funcionário precisa corrigir (obrigatório)',
                button: 'Pedir correção',
                required: true,
            } : {
                title: 'Devolver para a conferência?',
                text: 'A despesa volta para a conferência, que responde com uma explicação ou pede a correção ao funcionário.',
                label: 'O que precisa ser explicado ou corrigido (obrigatório)',
                button: 'Devolver',
                required: true,
            };
        }
        if (!control) {
            return {
                title: `Aprovar a despesa #${expense.id}?`,
                text: `Valor reembolsado: ${expense.reimbursed_total}. A aprovação encerra a despesa e dispara o lançamento no RM.`,
                label: 'Observação (opcional)',
                button: 'Aprovar',
                required: false,
            };
        }
        return expense.explanation_required ? {
            title: 'Explicar e aprovar?',
            text: 'A despesa volta para a validação com a sua explicação.',
            label: 'Explicação para a validação (obrigatória)',
            button: 'Enviar para a validação',
            required: true,
        } : {
            title: 'Aprovar e enviar para a validação?',
            text: `Valor reembolsado: ${formatMoney(totals().reimbursed)}.`,
            label: 'Observação (opcional)',
            button: 'Aprovar',
            required: false,
        };
    }

    document.querySelectorAll('[data-action]').forEach((button) => button.addEventListener('click', async () => {
        const expense = state.expense;
        if (!expense) return;
        clearMessages();
        const action = button.dataset.action;
        const note = await askNote(actionDialog(action, expense));
        if (note === null) return;

        const payload = { action, note, version: expense.version };
        if (canEdit()) payload.data = formData();
        const buttons = document.querySelectorAll('[data-action]');
        buttons.forEach((item) => { item.disabled = true; });
        try {
            const data = await postJson(urlFor('actionUrl', expense.id), payload);
            renderDetail(data.expense);
            showSuccess(`Despesa #${expense.id}: ${data.expense.status_display}.`);
        } catch (error) {
            showError(error.message);
            markInvalid(error.data && error.data.errors);
        } finally {
            buttons.forEach((item) => { item.disabled = false; });
            refreshApproveHint();
        }
    }));

    // ---------- Nova leitura pela IA ----------

    rereadButton.addEventListener('click', async () => {
        const expense = state.expense;
        if (!expense || !expense.can.reread) return;
        clearMessages();
        // O que a conferência já digitou e não gravou continua na tela: a leitura só completa o que está vazio
        const typed = Object.fromEntries(Object.entries(fieldInputs).map(([name, input]) => [name, input.value]));
        const typedItems = state.items;
        rereadButton.disabled = true;
        const label = rereadButton.innerHTML;
        rereadButton.textContent = 'Lendo a nota... isso pode levar até um minuto.';
        try {
            const data = await postJson(urlFor('readingUrl', expense.id), { version: expense.version });
            renderDetail(data.expense);
            for (const [name, value] of Object.entries(typed)) {
                if (value) fieldInputs[name].value = value;
            }
            if (typedItems.length) {
                state.items = typedItems;
                renderItems();
            }
            showSuccess('A IA leu a nota. Confira os dados antes de aprovar.');
        } catch (error) {
            showError(error.message);
            if (error.status === 409) loadDetail(expense.id);
        } finally {
            rereadButton.innerHTML = label;
            rereadButton.disabled = false;
        }
    });

    // ---------- Exclusão ----------

    const discardButton = document.getElementById('discard-button');
    if (discardButton) {
        discardButton.addEventListener('click', async () => {
            const expense = state.expense;
            if (!expense) return;
            clearMessages();
            const confirmed = await askNote({
                title: `Excluir a despesa #${expense.id}?`,
                text: 'A despesa e as fotos serão apagadas de vez. Se precisar, você pode enviar a nota de novo.',
                button: 'Excluir',
                danger: true,
                withNote: false,
            });
            if (confirmed === null) return;
            discardButton.disabled = true;
            try {
                await api(urlFor('expenseUrl', expense.id), { method: 'DELETE' });
                state.flash = `Despesa #${expense.id} excluída.`;
                navigate(content.dataset.pageUrl);
            } catch (error) {
                showError(error.message);
                // Alguém tratou a despesa nesse meio tempo: a tela mostra como ela está agora
                if (error.status === 409) loadDetail(expense.id);
            } finally {
                discardButton.disabled = false;
            }
        });
    }

    // ---------- Reenvio ----------

    if (access.employee) {
        const resendButton = document.getElementById('resubmit-send');
        const resendNote = document.getElementById('resubmit-note');
        const progress = progressView('resubmit', 'Fotos enviadas. Analisando as fotos... isso pode levar até um minuto.');
        const picker = photoPicker('resubmit', (count, busy) => {
            resendButton.disabled = count === 0 || busy || uploading;
        });

        resendButton.addEventListener('click', async () => {
            const expense = state.expense;
            clearMessages();
            resendButton.disabled = true;
            uploading = true;
            progress.sending(0);
            try {
                const data = await upload(urlFor('photosUrl', expense.id), photosForm(picker.files(), resendNote.value), progress);
                picker.clear();
                resendNote.value = '';
                renderDetail(data.expense);
                window.scrollTo(0, 0);
                showSuccess('Fotos reenviadas. A despesa volta para a conferência.');
            } catch (error) {
                showError(error.message);
            } finally {
                uploading = false;
                progress.hide();
                resendButton.disabled = picker.files().length === 0;
            }
        });
    }

    form.addEventListener('submit', (event) => event.preventDefault());

    // ---------- Início ----------

    route();
})();
