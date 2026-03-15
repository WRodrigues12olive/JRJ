let myOrders = window.MOTOBOY_ORDERS || []; 
let activeOs = null;

let isInteracting = false;
let isModalOpen = false;

document.addEventListener('mousedown', () => isInteracting = true);
document.addEventListener('mouseup', () => isInteracting = false);
document.addEventListener('touchstart', () => isInteracting = true);
document.addEventListener('touchend', () => isInteracting = false);

// ====================================================
// REGRA DE OURO LOGÍSTICA (Bloqueio Inteligente)
// ====================================================
const isActionableStop = (stop, index, allStops) => {
    // Bloqueio absoluto se a moto quebrou
    if (window.MOTOBOY_IS_AVAILABLE === false) return false;
    
    if (stop.is_completed) return false;
    if (stop.is_waiting_rescue) return false;
    if (stop.is_failed && !stop.bloqueia_proxima) return false;

    // 👇 Se for ENTREGA ou DEVOLUCAO: bloqueia só se a coleta DESTA OS falhou. Em OS mesclada, entregas de outras OS (coleta ok) podem ser concluídas.
    if (allStops && (stop.type === 'ENTREGA' || stop.type === 'DEVOLUCAO')) {
        const osDestaParada = stop.os_origem;
        const failedColeta = allStops.find(s => s.type === 'COLETA' && s.os_origem === osDestaParada && s.is_failed && !s.is_completed);
        if (failedColeta) {
            return false;
        }
    }
    return true;
};

function getCleanAddress(stop) {
    let addr = stop.address || '';
    if (stop.type === 'TRANSFERENCIA' || stop.type === 'DEVOLUCAO') {
        if (addr.includes('Encontro:')) {
            addr = addr.replace('Encontro:', '').trim();
        } else if (addr.includes('Devolver em:')) {
            addr = addr.replace('Devolver em:', '').trim();
        } else if (addr.includes(':')) {
            addr = addr.split(':').slice(1).join(':').trim();
        }
        
        if (!addr || addr === '') {
            addr = "Base da Empresa / Endereço não especificado";
        }
    }
    return addr;
}

function renderList() {
    const container = document.getElementById('os-list-container');
    let totalEntregasPendentes = 0; 
    container.innerHTML = '';

    if (myOrders.length === 0) {
        container.innerHTML = `
            <div class="d-flex flex-column align-items-center justify-content-center h-100 text-slate-400 mt-5">
                <i class="bi bi-check-circle fs-1 mb-2 opacity-50"></i>
                <p class="small fw-bold">Tudo limpo por aqui!</p>
            </div>
        `;
        document.getElementById('kpi-entregas') && (document.getElementById('kpi-entregas').innerText = "0");
        return;
    }

    // Descobre qual é a primeira OS que REALMENTE tem alguma parada acionável
    let firstActionableIndex = null;
    myOrders.forEach((os, index) => {
        const hasAnyActionable = os.stops.some(s => isActionableStop(s, null, os.stops));
        if (hasAnyActionable && firstActionableIndex === null) {
            firstActionableIndex = index;
        }
    });

    myOrders.forEach((os, index) => {
        const entregasPendentes = os.stops.filter(isActionableStop).filter(s => s.type === 'ENTREGA');
        totalEntregasPendentes += entregasPendentes.length;
        
        const paradasPendentes = os.stops.filter(isActionableStop);
        const nextStop = paradasPendentes.length > 0 ? paradasPendentes[0] : null;
        
        const hasWaitingRescue = os.stops.some(s => !s.is_completed && s.is_waiting_rescue);
        const hasPendingFailures = os.stops.some(s => s.is_failed && !s.is_completed);
        
        let iconBgClass, iconColorClass, iconClass;
        if (nextStop && nextStop.type === 'COLETA') {
            iconBgClass = 'bg-warning bg-opacity-10'; iconColorClass = 'text-warning'; iconClass = 'bi-box-seam';
        } else if (nextStop && nextStop.type === 'ENTREGA') {
            iconBgClass = 'bg-primary bg-opacity-10'; iconColorClass = 'text-primary'; iconClass = 'bi-geo-alt';
        } else if (nextStop && nextStop.type === 'TRANSFERENCIA') {
            iconBgClass = 'bg-danger bg-opacity-10'; iconColorClass = 'text-danger'; iconClass = 'bi-truck';
        } else {
            iconBgClass = 'bg-info bg-opacity-10'; iconColorClass = 'text-info'; iconClass = 'bi-arrow-return-left';
        }

        const hasAnyActionable = os.stops.some(s => isActionableStop(s, null, os.stops));
        // Nova regra: apenas as OS DEPOIS da primeira OS acionável ficam travadas.
        // OS que estão totalmente congeladas/aguardando despachante não travam a nova OS normal.
        const isLocked = firstActionableIndex !== null && index > firstActionableIndex && hasAnyActionable;

        const card = document.createElement('div');
        card.className = `bg-white p-3 rounded-4 shadow-sm border border-slate-200 mb-3 position-relative overflow-hidden transition-all ${isLocked ? 'opacity-75' : ''}`;
        card.style.cursor = isLocked ? "not-allowed" : "pointer";
        
        card.onclick = () => {
            if (isLocked) {
                showToast('🚨 Conclua a sua OS atual antes de iniciar a próxima!', false);
            } else {
                openOS(os.id);
            }
        };

        const mescladaBadge = os.has_children 
            ? `<div class="rounded-3 px-2 py-1 mb-2 d-inline-block small fw-bold w-100" style="background-color: #f3e8ff; color: #6b21a8; font-size: 0.7rem;"><i class="bi bi-diagram-3"></i> Múltiplas Entregas: Inclui ${os.child_numbers}</div>` 
            : '';

        let nextStopHTML = '';
        if (nextStop) {
            const previewAddress = getCleanAddress(nextStop);

            if (nextStop.is_frozen) {
                nextStopHTML = `
                <div class="alert alert-danger py-2 mb-0 mt-2 small fw-bold text-center border-danger">
                    <i class="bi bi-exclamation-triangle-fill"></i> ROTA SUSPENSA (Aguardando Decisão)
                </div>`;
            } else {
                nextStopHTML = `
                <div class="bg-slate-50 p-2 rounded-3 border border-light d-flex align-items-start gap-3 mt-2 ${isLocked ? 'grayscale' : ''}">
                    <div class="${iconBgClass} rounded-circle d-flex align-items-center justify-content-center mt-1 flex-shrink-0" style="width: 28px; height: 28px;">
                        <i class="bi ${iconClass} ${iconColorClass}"></i>
                    </div>
                    <div class="flex-grow-1 text-truncate">
                        <p class="text-slate-400 fw-bold text-uppercase mb-0" style="font-size: 0.6rem; letter-spacing: 1px;">Próxima Ação: ${nextStop.type}</p>
                        <p class="text-dark fw-bold text-truncate mb-0" style="font-size: 0.85rem;">${nextStop.name}</p>
                        <p class="text-slate-500 text-truncate mb-0" style="font-size: 0.7rem;">${previewAddress.split('-')[0]}</p>
                    </div>
                </div>`;
            }
        } else if (hasWaitingRescue) {
            nextStopHTML = `<div class="alert alert-warning py-2 mb-0 mt-2 small fw-bold text-center border-warning"><i class="bi bi-cone-striped"></i> Aguardando socorro / transferência de carga</div>`;
        } else if (hasPendingFailures) {
            nextStopHTML = `<div class="alert alert-warning py-2 mb-0 mt-2 small fw-bold text-center border-warning"><i class="bi bi-clock-history"></i> Aguardando Despachante (Ocorrência Aberta)</div>`;
        } else {
            nextStopHTML = `<div class="alert alert-success py-2 mb-0 mt-2 small fw-bold text-center"><i class="bi bi-check-circle"></i> Rota Finalizada</div>`;
        }

        let actionBtnHTML = '';
        if (window.MOTOBOY_IS_AVAILABLE === false) {
            actionBtnHTML = `
            <div class="w-100 py-2 mt-3 bg-danger bg-opacity-10 text-danger border border-danger border-opacity-25 rounded-3 small fw-bold d-flex align-items-center justify-content-center gap-2">
                <i class="bi bi-x-octagon-fill"></i> Bloqueado (Veículo Avariado)
            </div>`;
        } else if (isLocked) {
            actionBtnHTML = `
            <div class="w-100 py-2 mt-3 bg-secondary bg-opacity-10 text-secondary border border-secondary border-opacity-25 rounded-3 small fw-bold d-flex align-items-center justify-content-center gap-2">
                <i class="bi bi-lock-fill"></i> Aguardando OS anterior
            </div>`;
        } else if (nextStop && nextStop.is_frozen) {
            actionBtnHTML = `
            <div class="w-100 py-2 mt-3 bg-danger text-white rounded-3 small fw-bold d-flex align-items-center justify-content-center gap-2 shadow-sm">
                Ver Detalhes <i class="bi bi-chevron-right"></i>
            </div>`;
        } else if (!nextStop && hasPendingFailures) {
            actionBtnHTML = `
            <div class="w-100 py-2 mt-3 bg-warning bg-opacity-10 text-dark border border-warning border-opacity-25 rounded-3 small fw-bold d-flex align-items-center justify-content-center gap-2">
                <i class="bi bi-eye"></i> Ver Ocorrências
            </div>`;
        } else if (nextStop) {
            actionBtnHTML = `
            <div class="w-100 py-2 mt-3 bg-slate-900 text-white rounded-3 small fw-bold d-flex align-items-center justify-content-center gap-2 shadow-sm">
                Iniciar Roteiro <i class="bi bi-chevron-right"></i>
            </div>`;
        }
        card.innerHTML = `
            ${mescladaBadge}
            <div class="d-flex justify-content-between align-items-start mb-2">
                <span class="font-monospace fw-bold fs-5 text-dark">${os.os_number}</span>
                <span class="badge badge-prioridade-${os.priority} px-2 py-1" style="font-size: 0.65rem;">${os.priorityDisplay}</span>
            </div>
            
            <div class="d-flex justify-content-between align-items-center mb-3">
                <span class="badge bg-primary bg-opacity-10 text-primary border border-primary border-opacity-25 px-2 py-1" style="font-size: 0.7rem;">${os.status}</span>
                <span class="small fw-bold text-slate-500" style="font-size: 0.75rem;">${entregasPendentes.length} entregas aqui</span>
            </div>

            ${nextStopHTML}
            ${actionBtnHTML}
        `;
        container.appendChild(card);
    });

    document.getElementById('kpi-entregas') && (document.getElementById('kpi-entregas').innerText = totalEntregasPendentes);
}

// ====================================================
// NOVO: Atualiza a tela AO VIVO, mesmo dentro da OS!
// ====================================================
function autoRefreshMotoboy() {
    if (isInteracting || isModalOpen) return;

    fetch(window.location.href)
        .then(res => res.text())
        .then(html => {
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');

            const currentKpiRow = document.querySelector('.row.g-2.px-1.pb-2');
            const newKpiRow = doc.querySelector('.row.g-2.px-1.pb-2');
            if (currentKpiRow && newKpiRow) {
                currentKpiRow.innerHTML = newKpiRow.innerHTML;
            }

            const scripts = doc.querySelectorAll('script');
            for (let s of scripts) {
                if (s.innerText.includes('window.MOTOBOY_ORDERS =')) {
                    eval(s.innerText);
                    myOrders = window.MOTOBOY_ORDERS || []; 
                    renderList(); 
                    
                    // MÁGICA VISUAL: Atualiza a tela de execução ao vivo sem piscar
                    if (document.getElementById('view-execution').classList.contains('active') && activeOs) {
                        const updatedOs = myOrders.find(o => o.id === activeOs.id);
                        if (updatedOs) {
                            openOS(updatedOs.id); 
                        } else {
                            closeOS(); 
                        }
                    }
                    break;
                }
            }
        })
        .catch(err => console.log('Silencioso: falha na sincronização', err));
}

function abrirModalOcorrencia() {
    if (!activeOs) return;
    const currentStopIndex = activeOs.stops.findIndex(isActionableStop);
    if (currentStopIndex === -1) return;
    const currentStop = activeOs.stops[currentStopIndex];

    const form = document.getElementById('occurrenceForm');
    form.action = `/minhas-entregas/problema/${currentStop.id}/`; 
    form.reset();
    setupEvidencePhotoUI();
    handleCausaChange(); 
    
    new bootstrap.Modal(document.getElementById('occurrenceModal')).show();
}

function handleCausaChange() {
    const causa = document.getElementById('ocCausa').value;
    const obs = document.getElementById('ocObservacao');
    const warning = document.getElementById('obsWarning');
    const boxPodeSeguir = document.getElementById('boxPodeSeguir');
    const chkPodeSeguir = document.getElementById('podeSeguir');

    if (causa === 'ACIDENTE') {
        chkPodeSeguir.checked = false;
        boxPodeSeguir.classList.add('opacity-50', 'bg-light');
        chkPodeSeguir.disabled = true;
    } else {
        chkPodeSeguir.checked = true;
        boxPodeSeguir.classList.remove('opacity-50', 'bg-light');
        chkPodeSeguir.disabled = false;
    }

    const obsObrigatoria = ['OUTRO', 'NAO_LOCALIZADO', 'RECUSA'].includes(causa);
    if (obsObrigatoria) {
        obs.required = true;
        warning.classList.remove('d-none');
        obs.classList.add('border-danger');
    } else {
        obs.required = false;
        warning.classList.add('d-none');
        obs.classList.remove('border-danger');
    }
}

function setupEvidencePhotoUI() {
    const fileInput = document.querySelector('input[name="evidencia_foto"]');
    if (!fileInput) return;
    
    // Se já existe o wrapper, apenas reseta visualmente
    const existingWrapper = document.getElementById('evidencia-wrapper');
    if (existingWrapper) {
        resetEvidenceUI();
        return;
    }
    
    // Cria a estrutura visual igual ao POD
    const wrapper = document.createElement('div');
    wrapper.id = 'evidencia-wrapper';
    wrapper.className = 'border border-2 border-secondary border-opacity-25 rounded-4 p-4 text-center bg-light mb-3 transition-all';
    wrapper.style.borderStyle = 'dashed';
    wrapper.style.cursor = 'pointer';
    wrapper.onclick = () => fileInput.click();
    
    const icon = document.createElement('i');
    icon.id = 'evidencia-icone';
    icon.className = 'bi bi-camera fs-1 text-slate-300';
    
    const text = document.createElement('p');
    text.id = 'evidencia-texto';
    text.className = 'mb-0 mt-2 small fw-bold text-slate-400';
    text.innerText = 'Toque para anexar foto (Opcional)';
    
    wrapper.appendChild(icon);
    wrapper.appendChild(text);
    
    // Insere antes do input original e esconde o input
    if (fileInput.parentNode) {
        fileInput.parentNode.insertBefore(wrapper, fileInput);
        fileInput.classList.add('d-none');
    }
    
    // Adiciona listener para atualizar a UI quando selecionar arquivo
    fileInput.addEventListener('change', function(e) {
        if (e.target.files.length > 0) {
            text.innerText = "Foto Anexada: " + e.target.files[0].name;
            text.classList.replace('text-slate-400', 'text-success');
            icon.className = 'bi bi-check-circle-fill fs-1 text-success';
            wrapper.classList.replace('border-secondary', 'border-success');
            wrapper.classList.remove('border-opacity-25');
            wrapper.classList.add('bg-success', 'bg-opacity-10');
        } else {
            resetEvidenceUI();
        }
    });
}

function resetEvidenceUI() {
    const text = document.getElementById('evidencia-texto');
    const icon = document.getElementById('evidencia-icone');
    const wrapper = document.getElementById('evidencia-wrapper');
    
    if (text) {
        text.innerText = 'Toque para anexar foto (Opcional)';
        text.classList.replace('text-success', 'text-slate-400');
    }
    if (icon) {
        icon.className = 'bi bi-camera fs-1 text-slate-300';
    }
    if (wrapper) {
        wrapper.classList.replace('border-success', 'border-secondary');
        wrapper.classList.add('border-opacity-25');
        wrapper.classList.remove('bg-success', 'bg-opacity-10');
    }
}

function openOS(id) {
    sessionStorage.setItem('reopenOsId', id); 
    
    activeOs = myOrders.find(o => o.id === id);
    
    const currentStopIndex = activeOs.stops.findIndex(isActionableStop);
    const currentStop = currentStopIndex !== -1 ? activeOs.stops[currentStopIndex] : null;
    const hasWaitingRescue = activeOs.stops.some(s => !s.is_completed && s.is_waiting_rescue);
    const hasPendingFailures = activeOs.stops.some(s => s.is_failed && !s.is_completed);
    
    const isDelivery = currentStop && currentStop.type === 'ENTREGA';

    document.getElementById('exec-os-number').innerText = activeOs.os_number;
    
    if (currentStopIndex !== -1) {
        document.getElementById('exec-etapa').innerText = `Etapa ${currentStopIndex + 1} de ${activeOs.stops.length}`;
    } else {
        document.getElementById('exec-etapa').innerText = `Análise do Despachante`;
    }

    const cardContainer = document.getElementById('exec-current-card');
    const bottomAction = document.getElementById('exec-bottom-action');

    if (currentStop) {
        let itemsTitle = 'Itens para Coletar';
        let btnText = 'Confirmar Coleta';
        let badgeClass = 'bg-warning bg-opacity-10 text-warning';

        if (currentStop.type === 'ENTREGA') {
            itemsTitle = 'Itens para Entregar Aqui';
            btnText = 'Confirmar Entrega';
            badgeClass = 'bg-primary bg-opacity-10 text-primary';
        } else if (currentStop.type === 'TRANSFERENCIA') {
            itemsTitle = 'Carga a ser transferida';
            btnText = 'Confirmar Encontro e Carga';
            badgeClass = 'bg-danger bg-opacity-10 text-danger';
        } else if (currentStop.type === 'DEVOLUCAO') {
            itemsTitle = 'Carga a ser devolvida';
            btnText = 'Confirmar Devolução';
            badgeClass = 'bg-info bg-opacity-10 text-info';
        }
        
        let itemsHTML = '<ul class="list-group list-group-flush mb-0">';
        currentStop.items_details.forEach(item => {
            itemsHTML += `
            <li class="list-group-item bg-transparent px-0 py-2 d-flex justify-content-between align-items-center border-bottom border-light">
                <div class="text-truncate me-2">
                    <span class="fw-black text-dark fs-6">${item.qty}x</span> 
                    <span class="text-secondary fw-bold ms-1" style="font-size: 0.85rem;">${item.desc}</span>
                </div>
                <span class="badge bg-secondary bg-opacity-10 text-secondary border border-secondary border-opacity-25 px-2 py-1">${item.type}</span>
            </li>`;
        });
        itemsHTML += '</ul>';
        
        const cleanAddress = getCleanAddress(currentStop);
        // Corrige o link do Maps (apenas com o endereço limpo)
        const navUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(cleanAddress)}`;
        
        // Prepara o HTML do complemento (só aparece se houver texto)
        const complementHTML = (currentStop.complement && currentStop.complement.trim() !== '') 
            ? `<p class="mb-0 text-secondary small fw-bold mt-1"><i class="bi bi-info-circle"></i> Comp: ${currentStop.complement}</p>` 
            : '';

        cardContainer.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3">
                <span class="badge ${badgeClass} border fw-bold text-uppercase" style="font-size: 0.65rem;">Próxima Ação: ${currentStop.type}</span>
                <span class="text-slate-400 fw-bold" style="font-size: 0.7rem;">Parada ${currentStop.sequence}</span>
            </div>
            
            <h3 class="fw-bold text-dark mb-2">${currentStop.name}</h3>
            
            <div class="d-flex align-items-start gap-2 mt-3 mb-4">
                <i class="bi bi-geo-alt fs-5 text-slate-400 mt-1"></i>
                <div>
                    <p class="text-dark fw-bold mb-0" style="font-size: 0.85rem;">${cleanAddress}</p>
                    ${complementHTML}
                    ${currentStop.reference && currentStop.reference !== 'Sem referência' ? `<p class="badge bg-warning bg-opacity-10 text-warning border border-warning border-opacity-25 mt-2 mb-0 p-1 text-wrap text-start">Ref: ${currentStop.reference}</p>` : ''}
                </div>
            </div>

            <div class="bg-slate-50 p-3 rounded-4 border border-light mb-3">
                <p class="text-slate-400 fw-bold text-uppercase mb-2" style="font-size: 0.65rem; letter-spacing: 1px;">
                    <i class="bi bi-box-seam text-dark"></i> ${itemsTitle}
                </p>
                ${itemsHTML}
            </div>

            <div class="bg-slate-50 p-3 rounded-4 border border-light mb-4 d-flex justify-content-between align-items-center">
                <div>
                    <p class="text-slate-400 fw-bold text-uppercase mb-0" style="font-size: 0.65rem;">Contato no local</p>
                    ${currentStop.contact && currentStop.contact !== '--' ? `<p class="fw-bold text-dark mb-0">${currentStop.contact}</p>` : `<p class="fw-bold text-slate-400 mb-0">Não informado</p>`}
                </div>
                ${currentStop.contact && currentStop.contact !== '--' ? `<a href="tel:${currentStop.contact.replace(/\D/g, '')}" class="btn btn-primary btn-sm rounded-pill fw-bold px-3 py-2 shadow-sm d-flex align-items-center gap-1"><i class="bi bi-telephone"></i> Ligar</a>` : ''}
            </div>

            <div class="d-flex gap-2">
                <a href="${navUrl}" target="_blank" class="btn btn-light text-primary fw-bold w-50 py-2 d-flex justify-content-center align-items-center gap-2 border shadow-sm">
                    <i class="bi bi-cursor"></i> Navegar
                </a>
                <button type="button" onclick="copiarReferencia('${currentStop.reference || ''}')" class="btn btn-light text-secondary fw-bold w-50 py-2 d-flex justify-content-center align-items-center gap-2 border shadow-sm">
                    <i class="bi bi-copy"></i> Copiar Ref.
                </button>
            </div>
        `;

        const actionBtns = document.getElementById('action-buttons-container');
        const frozenAlert = document.getElementById('frozen-alert-container');

        if (currentStop.is_frozen) {
            if(actionBtns) actionBtns.classList.add('d-none');
            if(frozenAlert) frozenAlert.classList.remove('d-none');
        } else {
            if(actionBtns) actionBtns.classList.remove('d-none');
            if(frozenAlert) frozenAlert.classList.add('d-none');
            
            const btnConfirmar = document.getElementById('btn-confirmar');
            document.getElementById('btn-confirmar-text').innerText = btnText;
            
            if (isDelivery) {
                btnConfirmar.className = "btn btn-primary w-100 py-3 rounded-4 fw-bold fs-6 text-white d-flex align-items-center justify-content-center gap-2 shadow-sm transition-transform active:scale-95";
            } else if (currentStop.type === 'TRANSFERENCIA' || currentStop.type === 'DEVOLUCAO') {
                btnConfirmar.className = "btn btn-dark w-100 py-3 rounded-4 fw-bold fs-6 text-white d-flex align-items-center justify-content-center gap-2 shadow-sm transition-transform active:scale-95";
            } else {
                btnConfirmar.className = "btn btn-warning w-100 py-3 rounded-4 fw-bold fs-6 text-dark d-flex align-items-center justify-content-center gap-2 shadow-sm transition-transform active:scale-95";
            }
            
            document.getElementById('form-confirmar-etapa').action = `/minhas-entregas/atualizar/${currentStop.id}/`;
        }
        
        bottomAction.classList.remove('d-none');

    } else {
        if (hasWaitingRescue) {
            cardContainer.innerHTML = `
                <div class="bg-warning text-dark p-4 rounded-4 text-center shadow-sm">
                    <i class="bi bi-cone-striped fs-1 mb-2"></i>
                    <h4 class="fw-bold">Aguardando Socorro</h4>
                    <p class="small mb-0">Esta OS está em transferência de carga. Aguarde ação do despachante/socorrista.</p>
                </div>
            `;
        } else if (hasPendingFailures) {
            cardContainer.innerHTML = `
                <div class="bg-warning bg-opacity-10 text-dark border border-warning p-4 rounded-4 text-center shadow-sm">
                    <i class="bi bi-clock-history fs-1 mb-2 text-warning"></i>
                    <h4 class="fw-bold">Aguardando Despachante</h4>
                    <p class="small mb-0">Você reportou um problema na coleta desta rota. A entrega correspondente foi pausada automaticamente. Aguarde a central decidir o próximo passo.</p>
                </div>
            `;
        } else {
            cardContainer.innerHTML = `
                <div class="bg-success text-white p-4 rounded-4 text-center shadow-sm">
                    <i class="bi bi-check-circle fs-1 mb-2"></i>
                    <h4 class="fw-bold">OS Finalizada!</h4>
                    <p class="small text-white-50 mb-0">Todas as etapas concluídas com sucesso.</p>
                </div>
            `;
        }
        bottomAction.classList.add('d-none');
    }

    const timeline = document.getElementById('exec-timeline');
    timeline.innerHTML = '<div class="timeline-line"></div>';

    activeOs.stops.forEach((stop, index) => {
        const isCompleted = stop.is_completed;
        const isFailed = stop.is_failed; 
        const isCurrent = index === currentStopIndex;
        
        let dotClass, iconHTML;
        
        if (isFailed) {
            dotClass = 'bg-danger border-danger';
            iconHTML = '<i class="bi bi-x text-white" style="font-size: 1rem;"></i>';
        } else if (isCompleted) {
            dotClass = 'bg-success border-success';
            iconHTML = '<i class="bi bi-check text-white" style="font-size: 1rem;"></i>';
        } else if (isCurrent) {
            dotClass = 'bg-white border-primary border-3';
            iconHTML = '<div class="bg-primary rounded-circle" style="width: 8px; height: 8px;"></div>';
        } else {
            dotClass = 'bg-light border-slate-300';
            iconHTML = '';
        }
        
        let typeBadge = 'bg-primary bg-opacity-10 text-primary';
        if (stop.type === 'COLETA') typeBadge = 'bg-warning bg-opacity-10 text-warning';
        else if (stop.type === 'TRANSFERENCIA') typeBadge = 'bg-danger bg-opacity-10 text-danger';
        else if (stop.type === 'DEVOLUCAO') typeBadge = 'bg-info bg-opacity-10 text-info';

        const timelineEndereco = getCleanAddress(stop);

        timeline.innerHTML += `
            <div class="d-flex gap-3 position-relative z-1 mb-4 ${isCompleted ? 'opacity-50' : ''}">
                <div class="${dotClass} rounded-circle d-flex align-items-center justify-content-center mt-1 flex-shrink-0" style="width: 22px; height: 22px; z-index: 2;">
                    ${iconHTML}
                </div>
                <div class="flex-grow-1">
                    <div class="d-flex align-items-center gap-2 mb-1">
                        <span class="fw-bold text-slate-400" style="font-size: 0.7rem;">#${index + 1}</span>
                        <span class="badge ${typeBadge} px-2 border" style="font-size: 0.6rem;">${stop.type}</span>
                        ${activeOs.has_children ? `<span class="badge bg-light text-secondary border px-1" style="font-size: 0.55rem;">${stop.os_origem}</span>` : ''}
                    </div>
                    <p class="fw-bold mb-0 ${isCurrent ? 'text-dark fs-6' : 'text-slate-500 small'}">${stop.name}</p>
                    <p class="text-slate-400 mb-0 text-truncate" style="font-size: 0.7rem; max-width: 250px;">${timelineEndereco.split('-')[0]}</p>
                </div>
            </div>
        `;
    });

    document.getElementById('view-list').classList.remove('active');
    document.getElementById('view-execution').classList.add('active');
}

function closeOS() {
    document.getElementById('view-execution').classList.remove('active');
    document.getElementById('view-list').classList.add('active');
    activeOs = null;
    sessionStorage.removeItem('reopenOsId');
}

function copiarReferencia(texto) {
    if (!texto || texto === 'None' || texto.trim() === '' || texto === 'Sem referência') {
        showToast('Nenhuma referência disponível.', false);
        return;
    }
    navigator.clipboard.writeText(texto).then(() => showToast('Copiado!')).catch(() => showToast('Erro.', false));
}

function confirmarEtapa() {
    if (!activeOs) return;
    const currentStopIndex = activeOs.stops.findIndex(isActionableStop);
    if (currentStopIndex === -1) return;
    const currentStop = activeOs.stops[currentStopIndex];

    if (currentStop.type === 'ENTREGA') {
        const formPod = document.getElementById('form-pod');
        formPod.action = `/minhas-entregas/atualizar/${currentStop.id}/`; 
        
        document.getElementById('receiver_name').value = '';
        document.getElementById('proof_photo').value = '';
        document.getElementById('foto-texto').innerText = 'Toque aqui para abrir a câmera';
        document.getElementById('icone-camera').className = 'bi bi-camera fs-1 text-slate-300';
        document.getElementById('foto-texto').classList.replace('text-success', 'text-slate-400');
        
        new bootstrap.Modal(document.getElementById('podModal')).show();
    } else {
        const btn = document.getElementById('btn-confirmar');
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Processando...';
        btn.disabled = true;
        document.getElementById('form-confirmar-etapa').submit();
    }
}

document.getElementById('proof_photo')?.addEventListener('change', function(e) {
    if (e.target.files.length > 0) {
        document.getElementById('foto-texto').innerText = "Foto Anexada: " + e.target.files[0].name;
        document.getElementById('foto-texto').classList.replace('text-slate-400', 'text-success');
        document.getElementById('icone-camera').className = 'bi bi-check-circle-fill fs-1 text-success';
    }
});

function getCSRFToken() {
    const name = 'csrftoken';
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + '=') {
            return decodeURIComponent(cookie.substring(name.length + 1));
        }
    }
    const input = document.querySelector('[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
}

function setPresence(status, onSuccess) {
    const btn = document.getElementById('btn-iniciar-acesso') || document.getElementById('btn-voltar-online') || document.getElementById('btn-estou-ausente');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Atualizando...';
    }
    fetch('/motoboy/presenca/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken(),
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({ status: status })
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'ok' || data.presence) {
                if (typeof onSuccess === 'function') onSuccess();
                showToast(status === 'ONLINE' ? 'Você está online!' : 'Status ausente registrado.');
                setTimeout(() => window.location.reload(), 600);
            } else {
                showToast(data.message || 'Erro ao atualizar.', false);
                if (btn) { btn.disabled = false; btn.innerHTML = btn.getAttribute('data-original-html') || 'OK'; }
            }
        })
        .catch(() => {
            showToast('Erro de conexão. Tente de novo.', false);
            if (btn) { btn.disabled = false; btn.innerHTML = btn.getAttribute('data-original-html') || 'OK'; }
        });
}

function sendHeartbeat() {
    fetch('/motoboy/heartbeat/', {
        method: 'GET',
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).catch(() => console.log('Sem internet no momento.'));
}

function showToast(msg, isSuccess = true) {
    const toast = document.getElementById('toast');
    const icon = document.getElementById('toast-icon');
    document.getElementById('toast-msg').innerText = msg;
    icon.className = isSuccess ? 'bi bi-check-circle text-success' : 'bi bi-exclamation-triangle text-warning';
    toast.classList.remove('d-none');
    setTimeout(() => toast.classList.add('d-none'), 3000);
}

document.addEventListener('DOMContentLoaded', () => {
    renderList();
    
    const savedOsId = sessionStorage.getItem('reopenOsId');
    if (savedOsId) {
        const osExists = myOrders.find(o => o.id === savedOsId);
        if (osExists) openOS(savedOsId); 
        else sessionStorage.removeItem('reopenOsId');
    }

    const modalsIds = ['occurrenceModal', 'podModal'];
    modalsIds.forEach(id => {
        const el = document.getElementById(id);
        if(el) {
            el.addEventListener('show.bs.modal', () => isModalOpen = true);
            el.addEventListener('hidden.bs.modal', () => isModalOpen = false);
        }
    });

    sendHeartbeat();
    setInterval(sendHeartbeat, 60000);
    setInterval(autoRefreshMotoboy, 35000);

    document.getElementById('btn-iniciar-acesso')?.addEventListener('click', function() {
        this.setAttribute('data-original-html', this.innerHTML);
        setPresence('ONLINE');
    });
    document.getElementById('btn-voltar-online')?.addEventListener('click', function() {
        this.setAttribute('data-original-html', this.innerHTML);
        setPresence('ONLINE');
    });
    document.getElementById('btn-estou-ausente')?.addEventListener('click', function() {
        this.setAttribute('data-original-html', this.innerHTML);
        setPresence('AUSENTE');
    });
});