function getCSRFToken() {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, 10) === ('csrftoken=')) {
                cookieValue = decodeURIComponent(cookie.substring(10));
                break;
            }
        }
    }
    if (!cookieValue) {
        const tokenInput = document.querySelector('[name=csrfmiddlewaretoken]');
        if (tokenInput) cookieValue = tokenInput.value;
    }
    return cookieValue;
}


// ====================================================
// MODAL DETALHES E ATRIBUIÇÃO (OS AGUARDANDO)
// ====================================================
let currentModalOsId = null;

function openDispatchModal(id, number, status, company, priority, date, originName, originAddress, notes, groupIds = null, groupNumbers = null) {
    currentModalOsId = id;
    document.getElementById('modalDispOsNumber').innerText = number;
    document.getElementById('modalDispOsStatus').innerText = status;
    document.getElementById('modalDispCompany').innerText = company;
    document.getElementById('modalDispPriority').innerText = priority;
    document.getElementById('modalDispDate').innerText = date;
    document.getElementById('modalDispOriginName').innerText = originName;
    document.getElementById('modalDispOriginAddress').innerText = originAddress;

    const notesContainer = document.getElementById('modalDispNotesContainer');
    const notesElement = document.getElementById('modalDispNotes');
    
    if (notesContainer && notesElement) {
        if (notes && notes.trim() !== '' && notes !== 'None') {
            notesElement.innerText = notes;
            notesContainer.classList.remove('d-none');
        } else {
            notesElement.innerText = '';
            notesContainer.classList.add('d-none');
        }
    }
    
    const groupBox = document.getElementById('modalGroupBox');
    const groupContent = document.getElementById('modalGroupContent');
    
    if (groupBox && groupContent) {
        const hasGroup = groupIds && groupIds.trim() !== '';
        if (!hasGroup) {
            groupContent.innerHTML = '';
            groupBox.classList.add('d-none');
        } else {
            const ids = groupIds.split(',').map(s => s.trim()).filter(Boolean);
            const numbers = (groupNumbers || '').split(',').map(s => s.trim());

            let html = '';
            ids.forEach((cid, idx) => {
                const num = numbers[idx] || '';
                html += `
                    <div class="bg-white border border-warning border-opacity-25 p-2 rounded-3 d-flex justify-content-between align-items-center shadow-sm mb-2">
                        <span class="small fw-bold text-dark d-flex align-items-center gap-2">
                            <i class="bi bi-box-seam text-warning"></i> OS ${num || cid}
                        </span>
                        <button type="button"
                                class="btn btn-outline-danger btn-sm text-uppercase fw-bold px-3 py-1 transition-all"
                                style="font-size: 0.7rem;"
                                onclick="desfazerMescla('${cid}')">
                            <i class="bi bi-link-45deg fs-6 align-middle"></i> Desvincular
                        </button>
                    </div>
                `;
            });
            groupContent.innerHTML = html;
            groupBox.classList.remove('d-none');
        }
    }

    const assignBox = document.getElementById('modalAssignBox');
    if (status === 'PENDENTE') assignBox.classList.remove('d-none');
    else assignBox.classList.add('d-none');

    fetchAndRenderStops(id);

    var modal = new bootstrap.Modal(document.getElementById('dispatchOsModal'));
    modal.show();
}

function submitModalAssign() {
    const motoboyId = document.getElementById('modalCourierSelect').value;
    if (!motoboyId) { alert("⚠️ Selecione um técnico na lista para atribuir a OS."); return; }
    if (!currentModalOsId) return;
    assignMotoboySecurely(currentModalOsId, motoboyId);
}

function confirmCancelOS() {
    if(!currentModalOsId) return;
    if(confirm("🚨 ATENÇÃO: Tem certeza que deseja cancelar definitivamente esta OS? A empresa será notificada.")) {
        fetch(`/os/${currentModalOsId}/cancelar/`, {
            method: 'POST',
            headers: {'X-CSRFToken': getCSRFToken()}
        }).then(response => {
            if(response.ok) window.location.reload();
            else alert('Erro: A OS já está em andamento ou você não tem permissão.');
        });
    }
}

function verOSCompleta() {
    if (!currentModalOsId) return;
    // Redireciona para a nova página de detalhes completos da OS
    window.location.href = `/os/${currentModalOsId}/detalhes/`;
}
// ====================================================
// NOVO SISTEMA DE OCORRÊNCIAS (FASE 4)
// ====================================================
let currentHasExtraCargo = false;
let currentOccurrenceOsId = null;

function openDecisionModal(occurrenceId, osId, causaText, obsText, fotoUrl, causaCode = '', stopType = '', hasExtraCargo = 'false', osNumber = '', originName = '', destinationName = '', localAddress = '') {
    document.getElementById('currentOccurrenceId').value = occurrenceId;
    currentOccurrenceOsId = osId;
    document.getElementById('currentOccurrenceCauseCode').value = causaCode || '';
    document.getElementById('currentOccurrenceStopType').value = stopType || '';
    document.getElementById('decCausa').innerText = causaText || '—';
    document.getElementById('decObs').innerText = obsText || 'Sem observacoes.';

    document.getElementById('decOsNumber').innerText = osNumber ? 'OS ' + osNumber : '—';
    var paradaContext = '';
    if (stopType === 'COLETA') paradaContext = 'Coleta em ' + (originName || '—');
    else if (stopType === 'ENTREGA') paradaContext = 'Entrega para ' + (destinationName || '—');
    else if (stopType === 'DEVOLUCAO') paradaContext = 'Devolução';
    else if (stopType === 'TRANSFERENCIA') paradaContext = 'Transferência';
    else paradaContext = 'Parada ' + (stopType || '—');
    document.getElementById('decParadaContext').innerText = paradaContext;
    document.getElementById('decLocal').innerText = localAddress || '—';

    currentHasExtraCargo = hasExtraCargo === 'true';
    
    const fotoBox = document.getElementById('decFotoBox');
    const fotoLink = document.getElementById('decFotoLink');
    
    if (fotoUrl && fotoUrl !== 'None' && fotoUrl !== '') {
        fotoLink.href = fotoUrl;
        fotoBox.classList.remove('d-none');
    } else {
        fotoBox.classList.add('d-none');
    }

    document.getElementById('transferDecisionBox').classList.add('d-none');

    const canSuggestNewAddress = causaCode === 'NAO_LOCALIZADO' && (stopType === 'COLETA' || stopType === 'ENTREGA');
    const toggleBtn = document.getElementById('toggleNewAddressBtn');
    const reagendarBox = document.getElementById('reagendarAddressBox');
    if (toggleBtn) toggleBtn.classList.toggle('d-none', !canSuggestNewAddress);
    if (reagendarBox) reagendarBox.classList.add('d-none');

    const transferFields = [
        'decTransferCep',
        'decTransferStreet',
        'decTransferNumber',
        'decTransferComplement',
        'decTransferDistrict',
        'decTransferCity',
        'decTransferState',
        'localEncontro'
    ];
    transferFields.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });

    const reagendarFields = [
        'reagendarCep',
        'reagendarStreet',
        'reagendarNumber',
        'reagendarComplement',
        'reagendarDistrict',
        'reagendarCity',
        'reagendarState'
    ];
    reagendarFields.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });

    new bootstrap.Modal(document.getElementById('decisionModal')).show();
}

function toggleTransferBox() {
    const box = document.getElementById('transferDecisionBox');
    box.classList.toggle('d-none');
    
    const extraCargoAlert = document.getElementById('extraCargoAlert');
    if (extraCargoAlert) {
        if (!box.classList.contains('d-none') && currentHasExtraCargo) {
            extraCargoAlert.classList.remove('d-none');
        } else {
            extraCargoAlert.classList.add('d-none');
        }
    }
}

function toggleReagendarAddressBox() {
    const box = document.getElementById('reagendarAddressBox');
    if (box) box.classList.toggle('d-none');
}

function submitDecision(acao) {
    const occId = document.getElementById('currentOccurrenceId').value;
    const causaCode = document.getElementById('currentOccurrenceCauseCode')?.value || '';
    const stopType = document.getElementById('currentOccurrenceStopType')?.value || '';
    const canSuggestNewAddress = causaCode === 'NAO_LOCALIZADO' && (stopType === 'COLETA' || stopType === 'ENTREGA');
    const reagendarBox = document.getElementById('reagendarAddressBox');

    const payload = { acao: acao };
    if (acao === 'REAGENDAR' && canSuggestNewAddress && reagendarBox && !reagendarBox.classList.contains('d-none')) {
        const novoEndereco = {
            cep: document.getElementById('reagendarCep')?.value || '',
            street: document.getElementById('reagendarStreet')?.value || '',
            number: document.getElementById('reagendarNumber')?.value || '',
            complement: document.getElementById('reagendarComplement')?.value || '',
            district: document.getElementById('reagendarDistrict')?.value || '',
            city: document.getElementById('reagendarCity')?.value || '',
            state: document.getElementById('reagendarState')?.value || ''
        };

        const hasAny = Object.values(novoEndereco).some(v => (v || '').trim() !== '');
        if (hasAny) {
            if (!novoEndereco.street.trim() || !novoEndereco.city.trim()) {
                alert('Preencha pelo menos Rua e Cidade para atualizar o endereco.');
                return;
            }
            payload.incluir_novo_endereco = true;
            payload.novo_endereco = novoEndereco;
        }
    }
    
    fetch(`/orders/occurrence/${occId}/resolve/`, { 
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken() // <-- Usando a funcao mais segura
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if(data.status === 'success') {
            window.location.reload(); 
        } else {
            alert('Erro: ' + data.message);
        }
    });
}

function buscarCepReagendar(cep) {
    cep = (cep || '').replace(/\D/g, '');
    if (cep.length !== 8) return;
    fetch(`https://viacep.com.br/ws/${cep}/json/`)
        .then(res => res.json())
        .then(data => {
            if (!data.erro) {
                const street = document.getElementById('reagendarStreet');
                const district = document.getElementById('reagendarDistrict');
                const city = document.getElementById('reagendarCity');
                const state = document.getElementById('reagendarState');
                const number = document.getElementById('reagendarNumber');
                if (street) street.value = data.logradouro || '';
                if (district) district.value = data.bairro || '';
                if (city) city.value = data.localidade || '';
                if (state) state.value = data.uf || '';
                if (number) number.focus();
            } else {
                alert('CEP nao encontrado.');
            }
        })
        .catch(err => console.error(err));
}

function submitTransfer() {
    const occId = document.getElementById('currentOccurrenceId').value;
    const motoboyId = document.getElementById('socorristaSelect').value;
    const cep = document.getElementById('decTransferCep')?.value || '';
    const street = document.getElementById('decTransferStreet')?.value || '';
    const number = document.getElementById('decTransferNumber')?.value || '';
    const complement = document.getElementById('decTransferComplement')?.value || '';
    const district = document.getElementById('decTransferDistrict')?.value || '';
    const city = document.getElementById('decTransferCity')?.value || '';
    const state = document.getElementById('decTransferState')?.value || '';
    
    if(!motoboyId) { alert("Selecione o motoboy socorrista."); return; }

    const hasAnyAddress = [street, number, district, city, state, cep, complement].some(v => (v || '').trim() !== '');
    let local = document.getElementById('localEncontro')?.value || '';
    let complementoTransfer = (complement || '').trim();
    if (hasAnyAddress) {
        // Endereço limpo (sem complemento) para Google Maps
        const parts = [];
        if (street) {
            let streetLine = (street || '').trim();
            if (number) streetLine += ', ' + (number || '').trim();
            parts.push(streetLine);
        }
        if (district) parts.push('Bairro: ' + (district || '').trim());
        if (city || state) parts.push((city || '').trim() + (city && state ? '/' : '') + (state || '').trim());
        if (cep) parts.push('CEP: ' + (cep || '').trim());
        local = parts.join(' - ');
    }

    const transferAllCargoEl = document.getElementById('transfer_all_cargo');
    const transferAllCargo = transferAllCargoEl && currentHasExtraCargo ? transferAllCargoEl.checked : false;
    
    fetch(`/orders/occurrence/${occId}/resolve/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken() // <-- Usando a função mais segura
        },
        body: JSON.stringify({ 
            acao: 'TRANSFERIR_MOTOBOY',
            novo_motoboy_id: motoboyId,
            local_encontro: local,
            complemento_transfer: complementoTransfer,
            'furar_fila': document.getElementById('furar_fila').checked,
            'transfer_all_cargo': transferAllCargo
        })
    })
    .then(response => response.json())
    .then(data => {
        if(data.status === 'success') {
            alert('Transferência executada com segurança!');
            window.location.reload();
        } else {
            alert('Erro: ' + data.message);
        }
    });
}

// ====================================================
// ARRASTAR E SOLTAR DA OS E MESCLAGEM
// ====================================================
function drag(ev, osId) { ev.dataTransfer.setData("osId", osId); }
function allowDrop(ev) { ev.preventDefault(); ev.currentTarget.classList.add('drag-over'); }
function dragLeave(ev) { ev.currentTarget.classList.remove('drag-over'); }

function dropAssign(ev, motoboyId) {
    ev.preventDefault();
    ev.currentTarget.classList.remove('drag-over');
    var osId = ev.dataTransfer.getData("osId");
    if (!osId) return;
    assignMotoboySecurely(osId, motoboyId);
}

function allowOsDrop(ev) { ev.preventDefault(); ev.currentTarget.classList.add('drag-over-os'); }
function leaveOsDrop(ev) { ev.currentTarget.classList.remove('drag-over-os'); }

function dropMerge(ev, targetOsId) {
    ev.preventDefault();
    ev.currentTarget.classList.remove('drag-over-os');
    const sourceOsId = ev.dataTransfer.getData("osId");

    if (!sourceOsId || sourceOsId === targetOsId) return;

    if(confirm("🔗 FUSÃO DE ROTAS\n\nDeseja mesclar essas duas Ordens de Serviço? A OS arrastada acompanhará a principal.")) {
        document.body.style.cursor = 'wait';
        
        fetch('/os/mesclar/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json', 
                'X-CSRFToken': getCSRFToken() 
            },
            body: JSON.stringify({ source_os: sourceOsId, target_os: targetOsId })
        })
        .then(res => {
            if (!res.ok) throw new Error("Erro no servidor (Status " + res.status + ")");
            return res.json();
        })
        .then(data => {
            document.body.style.cursor = 'default';
            if(data.status === 'success') window.location.reload(); 
            else alert("Erro do sistema: " + data.message);
        })
        .catch(err => {
            document.body.style.cursor = 'default';
            alert("Falha na mesclagem: " + err.message);
            console.error(err);
        });
    }
}

function desfazerMescla(childOsId) {
    if (!childOsId) return;
    if (!confirm("⚠️ Deseja DESFAZER a mescla desta OS e devolvê-la para a fila como independente?")) return;

    document.body.style.cursor = 'wait';

    fetch('/os/desfazer-mescla/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify({ child_os: childOsId })
    })
    .then(res => {
        if (!res.ok) throw new Error("Erro no servidor (Status " + res.status + ")");
        return res.json();
    })
    .then(data => {
        document.body.style.cursor = 'default';
        if (data.status === 'success') window.location.reload();
        else alert("Erro do sistema: " + (data.message || 'Falha ao desfazer mescla.'));
    })
    .catch(err => {
        document.body.style.cursor = 'default';
        alert("Falha ao desfazer mescla: " + err.message);
        console.error(err);
    });
}

function assignMotoboySecurely(osId, motoboyId) {
    document.body.style.cursor = 'wait';
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = `/painel-despacho/atribuir/${osId}/`;
    
    const inputCsrf = document.createElement('input');
    inputCsrf.type = 'hidden';
    inputCsrf.name = 'csrfmiddlewaretoken';
    inputCsrf.value = getCSRFToken();
    form.appendChild(inputCsrf);
    
    const inputMotoboy = document.createElement('input');
    inputMotoboy.type = 'hidden';
    inputMotoboy.name = 'motoboy_id';
    inputMotoboy.value = motoboyId;
    form.appendChild(inputMotoboy);
    
    document.body.appendChild(form);
    form.submit();
}

// ====================================================
// ROTEIRIZAÇÃO E TIMELINE (MODAL)
// ====================================================
let modalSortableInstance = null;
const DISPATCH_PANEL_CONFIG = window.DISPATCH_PANEL_CONFIG || {};

function fetchAndRenderStops(osId) {
    const list = document.getElementById('modalRouteTimeline');
    list.innerHTML = '<li class="list-group-item text-center text-muted border-0"><span class="spinner-border spinner-border-sm"></span> Carregando rota...</li>';

    fetch(`/os/${osId}/stops/`)
    .then(res => res.json())
    .then(data => {
        list.innerHTML = '';
        data.stops.forEach(stop => {
            const isColeta = stop.type === 'COLETA';
            const icon = isColeta ? '<i class="bi bi-box-arrow-up text-danger fs-4"></i>' : '<i class="bi bi-box-arrow-down text-success fs-4"></i>';
            const badgeColor = isColeta ? 'bg-danger' : 'bg-success';
            const mapsQuery = (stop.address || '').replace(/^\(OS [^)]+\)\s*/, '');
            const mapsUrl = `https://www.google.com/maps?q=${encodeURIComponent(mapsQuery)}`;
            
            // 👇 Cria o campo de valor APENAS se for ENTREGA
            let valueInputHTML = '';
            if (!isColeta) {
                valueInputHTML = `
                    <div class="input-group input-group-sm me-2" style="width: 130px;" title="Alterar valor da entrega">
                        <span class="input-group-text bg-success bg-opacity-10 text-success fw-bold border-success">R$</span>
                        <input type="number" step="0.01" min="0" class="form-control border-success text-center fw-bold" 
                               value="${stop.value.toFixed(2)}" 
                               onchange="updateStopValue('${stop.id}', this.value)"
                               onfocus="isInteracting = true;" onblur="isInteracting = false;">
                    </div>
                `;
            }

            list.innerHTML += `
                <li class="list-group-item d-flex align-items-center gap-3 py-3" data-id="${stop.id}" data-type="${stop.type}" style="cursor: grab;">
                    <div class="d-flex flex-column align-items-center gap-1">
                        <span class="badge ${badgeColor} rounded-pill shadow-sm">${stop.sequence}º</span>
                    </div>
                    <div>${icon}</div>
                    <div class="flex-grow-1">
                        <strong class="text-dark d-block mb-1">${stop.location}</strong>
                        <small class="text-muted d-flex align-items-center gap-1"><i class="bi bi-geo-alt"></i> ${stop.address}</small>
                    </div>
                    
                    <div class="d-flex align-items-center">
                        ${valueInputHTML}
                        <a href="${mapsUrl}" target="_blank" class="btn btn-sm btn-outline-primary fw-bold text-nowrap">
                            <i class="bi bi-cursor"></i> Ver Local
                        </a>
                    </div>
                    <i class="bi bi-grip-vertical text-muted fs-5 ms-2"></i>
                </li>
            `;
        });

        if (modalSortableInstance) modalSortableInstance.destroy();

        modalSortableInstance = new Sortable(list, {
            animation: 150,
            ghostClass: 'bg-light',
            onStart: function() { isInteracting = true; },
            onEnd: function() {
                isInteracting = false;
                
                let stopIds = Array.from(list.children)
                    .map(item => item.dataset.id)
                    .filter(id => id !== undefined && id !== null && id !== "");
                
                const url = DISPATCH_PANEL_CONFIG.reorderStopsUrl || '/painel-despacho/reordenar-paradas/';

                fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json', 
                        'X-CSRFToken': getCSRFToken()
                    },
                    body: JSON.stringify({ stops: stopIds })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'success') {
                        fetchAndRenderStops(osId); 
                    } else {
                        // Se der erro (ex: colocou entrega antes de coleta), exibe o aviso e reverte a UI
                        alert("⚠️ " + data.message);
                        fetchAndRenderStops(osId);
                    }
                });
            }
        });
    });
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-content-col').forEach(el => { el.classList.remove('d-flex'); el.classList.add('d-none'); });
    const selectedCol = document.getElementById('col-' + tabId);
    selectedCol.classList.remove('d-none'); selectedCol.classList.add('d-flex');
    
    document.querySelectorAll('.mobile-tab').forEach(el => { el.classList.remove('border-bottom', 'border-primary', 'border-3', 'text-primary'); el.classList.add('text-secondary'); });
    const selectedTab = document.getElementById('tab-' + tabId);
    selectedTab.classList.remove('text-secondary'); selectedTab.classList.add('border-bottom', 'border-primary', 'border-3', 'text-primary');
}

// ====================================================
// ATUALIZAÇÃO AUTOMÁTICA DA PÁGINA
// ====================================================
let isInteracting = false;
let isModalOpen = false;

document.addEventListener('mousedown', () => isInteracting = true);
document.addEventListener('mouseup', () => isInteracting = false);
document.addEventListener('dragstart', () => isInteracting = true);
document.addEventListener('dragend', () => isInteracting = false);

// Atualiza para incluir o novo decisionModal
const modalsIds = ['dispatchOsModal', 'resolveProblemModal', 'transferRouteModal', 'createReturnModal', 'decisionModal'];
modalsIds.forEach(id => {
    document.getElementById(id)?.addEventListener('show.bs.modal', () => isModalOpen = true);
    document.getElementById(id)?.addEventListener('hidden.bs.modal', () => isModalOpen = false);
});

function autoRefreshDashboard() {
    if (isInteracting || isModalOpen) return; 

    fetch(window.location.href)
        .then(response => response.text())
        .then(html => {
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');

            document.getElementById('col-frota').innerHTML = doc.getElementById('col-frota').innerHTML;
            document.getElementById('col-aguardando').innerHTML = doc.getElementById('col-aguardando').innerHTML;
            document.getElementById('col-atendimento').innerHTML = doc.getElementById('col-atendimento').innerHTML;
        })
        .catch(error => console.log('Silencioso: Falha na autossincronização', error));
}
setInterval(autoRefreshDashboard, 10000);


// ====================================================
// SISTEMA LEGADO (MANTIDO PARA COMPATIBILIDADE DE OS ANTIGAS)
// ====================================================
let problemOsId = null;
let transferBeforePickup = false;

function abrirModalResolver(osId, osNumber, notes, stopType = null) {
    problemOsId = osId;
    transferBeforePickup = (stopType === 'COLETA');

    document.getElementById('modalProblemOsNumber').innerText = osNumber;
    document.getElementById('modalProblemNotes').innerText = notes || "Nenhuma observação registrada pelo motoboy.";
    
    var modal = new bootstrap.Modal(document.getElementById('resolveProblemModal'));
    modal.show();
}

function submitResolveAction(action) {
    if (!problemOsId) return;
    
    if (action === 'cancel') {
        if(confirm("Tem a certeza que deseja CANCELAR esta OS? A empresa será notificada.")) {
            document.body.style.cursor = 'wait';
            fetch(`/os/${problemOsId}/cancelar/`, {
                method: 'POST',
                headers: {'X-CSRFToken': getCSRFToken()}
            }).then(res => window.location.reload());
        }
        return;
    }

    document.body.style.cursor = 'wait';
    fetch(`/painel-despacho/resolver/${problemOsId}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify({ action: action })
    }).then(res => window.location.reload());
}

function openTransferModal() {
    var resolveModal = bootstrap.Modal.getInstance(document.getElementById('resolveProblemModal'));
    if(resolveModal) resolveModal.hide();

    const addrBox = document.getElementById('transferAddressBox');
    const intro = document.getElementById('transferIntroText');

    if (addrBox && intro) {
        if (transferBeforePickup) {
            addrBox.classList.add('d-none');
            intro.innerText = "Veículo avariado antes da coleta. O novo motoboy irá direto ao endereço original da OS para buscar a carga.";
        } else {
            addrBox.classList.remove('d-none');
            intro.innerText = "Escolha o motoboy socorrista e preencha os dados do local de encontro onde a carga será transferida.";
        }
    }
    var transferModal = new bootstrap.Modal(document.getElementById('transferRouteModal'));
    transferModal.show();
}

function openReturnModal() {
    var decisionModal = bootstrap.Modal.getInstance(document.getElementById('decisionModal'));
    if(decisionModal) decisionModal.hide();
    
    var returnModal = new bootstrap.Modal(document.getElementById('createReturnModal'));
    returnModal.show();
}
function preencherEnderecoBase() {
    const cepsEl = document.getElementById('returnCep');
    if (cepsEl) cepsEl.value = '90000-000'; 
    document.getElementById('returnStreet').value = 'Base da Transportadora';
    document.getElementById('returnNumber').value = 'S/N';
    document.getElementById('returnDistrict').value = 'Centro';
    document.getElementById('returnCity').value = 'Sua Cidade';
    document.getElementById('returnState').value = 'RS';
    document.getElementById('returnComplement').value = 'Setor de Triagem';
}

function buscarCepDevolucao(cep) {
    cep = cep.replace(/\D/g, '');
    if (cep.length !== 8) return;
    fetch(`https://viacep.com.br/ws/${cep}/json/`)
        .then(res => res.json())
        .then(data => {
            if (!data.erro) {
                document.getElementById('returnStreet').value = data.logradouro;
                document.getElementById('returnDistrict').value = data.bairro;
                document.getElementById('returnCity').value = data.localidade;
                document.getElementById('returnState').value = data.uf;
                document.getElementById('returnNumber').focus();
            } else alert("CEP não encontrado.");
        }).catch(err => console.error(err));
}

function buscarCepTransferencia(cep) {
    cep = cep.replace(/\D/g, '');
    if (cep.length !== 8) return;
    fetch(`https://viacep.com.br/ws/${cep}/json/`)
        .then(res => res.json())
        .then(data => {
            if (!data.erro) {
                document.getElementById('transferStreet').value = data.logradouro;
                document.getElementById('transferDistrict').value = data.bairro;
                document.getElementById('transferCity').value = data.localidade;
                document.getElementById('transferState').value = data.uf;
                document.getElementById('transferNumber').focus();
            } else alert("CEP não encontrado.");
        }).catch(err => console.error(err));
}

function submitTransferRoute() {
    if (!problemOsId) return;
    
    const newMotoboyId = document.getElementById('transferMotoboySelect').value;
    const cep = document.getElementById('transferCep').value;
    const street = document.getElementById('transferStreet').value;
    const number = document.getElementById('transferNumber').value;
    const complement = document.getElementById('transferComplement').value;
    const district = document.getElementById('transferDistrict').value;
    const city = document.getElementById('transferCity').value;
    const state = document.getElementById('transferState').value;

    if (!newMotoboyId) { alert("⚠️ Por favor, selecione o motoboy socorrista na lista!"); return; }
    let transferAddress = '';

    if (!transferBeforePickup) {
        const hasAny = [street, number, district, city, state, cep, complement].some(v => (v || '').trim() !== '');

        if (!hasAny) {
            alert("⚠️ Esta OS já foi carregada. Informe pelo menos um endereço de encontro para transferir a carga.");
            return;
        }

        // Endereço limpo (sem complemento) para Google Maps
        const partes = [];
        if (street) {
            let linha = street.trim();
            if (number) linha += ', ' + (number || '').trim();
            partes.push(linha);
        }
        if (district || city || state) {
            let linha2 = '';
            if (district) linha2 += (district || '').trim();
            if (city) linha2 += (linha2 ? ' - ' : '') + (city || '').trim();
            if (state) linha2 += (linha2 ? '/' : '') + (state || '').trim();
            if (linha2) partes.push(linha2);
        }
        if (cep) partes.push('CEP: ' + (cep || '').trim());
        transferAddress = partes.join(' | ');
    }

    const transferComplement = (complement || '').trim();

    document.body.style.cursor = 'wait';
    fetch(`/painel-despacho/transferir/${problemOsId}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
        body: JSON.stringify({ new_motoboy_id: newMotoboyId, transfer_address: transferAddress, transfer_complement: transferComplement })
    })
    .then(res => res.json())
    .then(data => {
        if(data.status === 'success') window.location.reload();
        else { alert("Erro ao transferir: " + data.message); document.body.style.cursor = 'default'; }
    });
}

function submitCreateReturn() {
    const occId = document.getElementById('currentOccurrenceId').value;
    if (!occId) return;
    
    const cep = document.getElementById('returnCep').value;
    const street = document.getElementById('returnStreet').value;
    const number = document.getElementById('returnNumber').value;
    const complement = document.getElementById('returnComplement').value;
    const district = document.getElementById('returnDistrict').value;
    const city = document.getElementById('returnCity').value;
    const state = document.getElementById('returnState').value;
    
    const priorityElem = document.getElementById('returnPriority');
    const isPriority = priorityElem ? priorityElem.checked : false;

    if (!street || !number || !district || !city) { 
        alert("⚠️ Por favor, preencha pelo menos a Rua, Número, Bairro e Cidade para a devolução!"); 
        return; 
    }

    // Endereço limpo (sem complemento) para busca no Google Maps
    const returnAddress = `${street.trim()}, ${number.trim()} - ${district.trim()}, ${city.trim()}/${(state || '').trim()}${cep ? ' - CEP: ' + cep : ''}`;
    const complementoRetorno = (complement || '').trim();

    document.body.style.cursor = 'wait';
    
    fetch(`/orders/occurrence/${occId}/resolve/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
        body: JSON.stringify({ 
            acao: 'RETORNAR', 
            endereco_retorno: returnAddress, 
            complemento_retorno: complementoRetorno,
            is_priority: isPriority 
        })
    })
    .then(res => res.json())
    .then(data => {
        if(data.status === 'success') window.location.reload();
        else { alert("Erro ao agendar devolução: " + data.message); document.body.style.cursor = 'default'; }
    });
}

function buscarCepTransferenciaDecisao(cep) {
    cep = (cep || '').replace(/\D/g, '');
    if (cep.length !== 8) return;
    fetch(`https://viacep.com.br/ws/${cep}/json/`)
        .then(res => res.json())
        .then(data => {
            if (!data.erro) {
                const street = document.getElementById('decTransferStreet');
                const district = document.getElementById('decTransferDistrict');
                const city = document.getElementById('decTransferCity');
                const state = document.getElementById('decTransferState');
                const number = document.getElementById('decTransferNumber');
                if (street) street.value = data.logradouro || '';
                if (district) district.value = data.bairro || '';
                if (city) city.value = data.localidade || '';
                if (state) state.value = data.uf || '';
                if (number) number.focus();
            } else {
                alert("CEP não encontrado.");
            }
        })
        .catch(err => console.error(err));
}

function verOSCompletaOcorrencia() {
    if (!currentOccurrenceOsId) return;
    window.location.href = `/os/${currentOccurrenceOsId}/detalhes/`;
}

function updateStopValue(stopId, newValue) {
    const finalValue = Math.max(0, parseFloat(newValue) || 0);

    fetch(`/os/parada/${stopId}/atualizar-valor/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify({ value: finalValue })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status !== 'success') alert('Erro ao atualizar valor.');
    });
}