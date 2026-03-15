const OS_CREATE_CONFIG = window.OS_CREATE_CONFIG || {};

// Máscaras
const formatCNPJ = (value) => {
    return value
        .replace(/\D/g, '')
        .replace(/^(\d{2})(\d)/, '$1.$2')
        .replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3')
        .replace(/\.(\d{3})(\d)/, '.$1/$2')
        .replace(/(\d{4})(\d)/, '$1-$2')
        .slice(0, 18);
};

const formatPhone = (value) => {
    return value
        .replace(/\D/g, '')
        .replace(/(\d{2})(\d)/, '($1) $2')
        .replace(/(\d{5})(\d)/, '$1-$2')
        .slice(0, 15);
};

const formatCEP = (value) => {
    return value
        .replace(/\D/g, '')
        .replace(/(\d{5})(\d)/, '$1-$2')
        .slice(0, 9);
};

// Busca CEP (ViaCEP)
async function buscarCEP(cepInput, type, cardElement = null) {
    let cep = cepInput.value.replace(/\D/g, '');
    if (cep.length !== 8) return;

    cepInput.style.opacity = '0.5';

    try {
        let response = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
        let data = await response.json();

        if (data.erro) {
            alert("CEP não encontrado!");
            cepInput.style.opacity = '1';
            return;
        }

        if (type === 'origem') {
            document.getElementById('orig_street').value = data.logradouro || '';
            document.getElementById('orig_district').value = data.bairro || '';
            document.getElementById('orig_city').value = data.localidade || '';
            document.getElementById('orig_state').value = data.uf || '';
            document.getElementById('orig_number').focus();
        } else if (type === 'destino' && cardElement) {
            cardElement.querySelector('.loc-street').value = data.logradouro || '';
            cardElement.querySelector('.loc-dist').value = data.bairro || '';
            cardElement.querySelector('.loc-city').value = data.localidade || '';
            cardElement.querySelector('.loc-state').value = data.uf || '';
            cardElement.querySelector('.loc-num').focus();
        }
    } catch (error) {
        console.error("Erro na busca de CEP:", error);
        alert("Erro ao buscar o CEP. Verifique sua conexão.");
    } finally {
        cepInput.style.opacity = '1';
    }
}

let itemIdCounter = 0;
let locIdCounter = 0;

document.addEventListener("DOMContentLoaded", () => {
    addItem();
    addLocation();
});

function addItem() {
    const template = document.getElementById('item-template');
    const clone = template.content.cloneNode(true);
    const card = clone.querySelector('.item-card');
    
    itemIdCounter++;
    card.dataset.id = `itm-${itemIdCounter}`;
    
    document.getElementById('items-container').appendChild(clone);
    syncItemsToLocations();
}

function removeItem(btn) {
    const container = document.getElementById('items-container');
    if (container.children.length <= 1) {
        alert("A OS precisa ter pelo menos 1 item!");
        return;
    }
    btn.closest('.item-card').remove();
    syncItemsToLocations();
}

function addLocation() {
    const template = document.getElementById('location-template');
    const clone = template.content.cloneNode(true);
    const card = clone.querySelector('.location-card');
    
    locIdCounter++;
    card.dataset.id = `loc-${locIdCounter}`;
    
    document.getElementById('locations-container').appendChild(clone);
    syncItemsToLocations();
}

function removeLocation(btn) {
    const container = document.getElementById('locations-container');
    if (container.children.length <= 1) {
        alert("A OS precisa ter pelo menos 1 destino!");
        return;
    }
    btn.closest('.location-card').remove();
}

function syncItemsToLocations() {
    const itemsList = [];
    document.querySelectorAll('.item-card').forEach(card => {
        const id = card.dataset.id;
        const desc = card.querySelector('.item-desc').value || "(Sem descrição)";
        const qty = parseInt(card.querySelector('.item-qty').value) || 1;
        const type = card.querySelector('.item-type').value;
        itemsList.push({ id, desc, qty, type });
    });

    document.querySelectorAll('.location-card').forEach(locCard => {
        const container = locCard.querySelector('.linked-items-container');
        const markedStates = {};
        const qtysEntered = {};
        
        container.querySelectorAll('.item-checkbox').forEach(chk => {
            markedStates[chk.value] = chk.checked;
            const qtyInput = container.querySelector(`.qty-input-${chk.value}`);
            if (qtyInput) qtysEntered[chk.value] = qtyInput.value;
        });

        container.innerHTML = ''; 

        if (itemsList.length === 0) {
            container.innerHTML = '<span class="text-muted small">Adicione itens primeiro.</span>';
            return;
        }

        itemsList.forEach(item => {
            const isChecked = markedStates[item.id] ? 'checked' : '';
            const savedQty = qtysEntered[item.id] || 1; 
            const showQty = markedStates[item.id] ? 'block' : 'none';
            const isDisabled = markedStates[item.id] ? '' : 'disabled'; 
            
            const html = `
                <div class="d-flex align-items-center gap-2 bg-white border rounded px-3 py-2 shadow-sm mb-2">
                    <input class="form-check-input item-checkbox mt-0 cursor-pointer" type="checkbox" value="${item.id}" ${isChecked} 
                           onchange="toggleQtyInput(this, '${locCard.dataset.id}', '${item.id}'); updateRemainingQuantities();">
                    <label class="form-check-label flex-grow-1 small fw-bold cursor-pointer" onclick="if(!this.previousElementSibling.disabled) this.previousElementSibling.click()">
                        ${item.desc} <span class="text-muted fw-normal">| Tipo: ${item.type} | <span class="disp-qty-text fw-bold text-primary">Restante: ${item.qty}</span></span>
                    </label>
                    <div class="qty-wrapper-${locCard.dataset.id}-${item.id}" style="display: ${showQty}; width: 80px;">
                        <input type="number" class="form-control form-control-sm border-primary qty-input-${item.id}" 
                            value="${savedQty}" min="1" max="${item.qty}" ${isDisabled} oninput="updateRemainingQuantities()">
                    </div>
                </div>
            `;
            container.insertAdjacentHTML('beforeend', html);
        });
    });
    
    updateRemainingQuantities();
}

function toggleQtyInput(checkbox, locId, itemId) {
    const wrapper = document.querySelector(`.qty-wrapper-${locId}-${itemId}`);
    wrapper.style.display = checkbox.checked ? 'block' : 'none';
    
    const input = document.querySelector(`.qty-wrapper-${locId}-${itemId} input`);
    if (input) {
        if (!checkbox.checked) {
            input.value = 1; 
            input.disabled = true;
        } else {
            input.disabled = false;
        }
    }
}

function updateRemainingQuantities() {
    const itemTotals = {};
    document.querySelectorAll('.item-card').forEach(card => {
        const id = card.dataset.id;
        itemTotals[id] = parseInt(card.querySelector('.item-qty').value) || 0;
    });

    const allocated = {};
    document.querySelectorAll('.location-card').forEach(locCard => {
        locCard.querySelectorAll('.item-checkbox:checked').forEach(chk => {
            const itemId = chk.value;
            const qtyInput = locCard.querySelector(`.qty-input-${itemId}`);
            allocated[itemId] = (allocated[itemId] || 0) + (parseInt(qtyInput.value) || 0);
        });
    });

    document.querySelectorAll('.location-card').forEach(locCard => {
        Object.keys(itemTotals).forEach(itemId => {
            const total = itemTotals[itemId];
            const usedTotal = allocated[itemId] || 0;
            const globalRemaining = total - usedTotal;

            const checkbox = locCard.querySelector(`.item-checkbox[value="${itemId}"]`);
            if (!checkbox) return;

            const qtyInput = locCard.querySelector(`.qty-input-${itemId}`);
            const usedHere = checkbox.checked ? (parseInt(qtyInput.value) || 0) : 0;

            const availableForThisInput = globalRemaining + usedHere;

            const labelSpan = checkbox.nextElementSibling.querySelector('.disp-qty-text');
            if (labelSpan) {
                labelSpan.textContent = `Restante: ${globalRemaining}`;
                if (globalRemaining <= 0 && !checkbox.checked) {
                    labelSpan.classList.replace('text-primary', 'text-danger');
                } else {
                    labelSpan.classList.replace('text-danger', 'text-primary');
                }
            }

            if (qtyInput) {
                qtyInput.max = availableForThisInput;
                if (parseInt(qtyInput.value) > availableForThisInput) {
                    qtyInput.value = availableForThisInput;
                    setTimeout(updateRemainingQuantities, 10);
                }
            }

            if (globalRemaining <= 0 && !checkbox.checked) {
                checkbox.disabled = true;
            } else {
                checkbox.disabled = false;
            }
        });
    });
}

function submitForm() {
    try {
        const form = document.getElementById('osForm');
        
        if (!form.checkValidity()) {
            alert("ATENÇÃO: Faltam campos obrigatórios!\nPor favor, preencha todas as caixinhas que possuem um asterisco (*) antes de gerar a OS.");
            form.reportValidity(); 
            return;
        }

        let payload = {
            requester_name: document.getElementById('req_name')?.value || '',
            requester_phone: document.getElementById('req_phone')?.value || '',
            company_cnpj: document.getElementById('req_cnpj')?.value || '',
            company_email: document.getElementById('req_email')?.value || '',
            delivery_type: document.getElementById('delivery_type')?.value || 'Normal',
            vehicle_type: document.getElementById('veh_type')?.value || 'MOTO',
            priority: document.getElementById('priority')?.value || 'NORMAL',
            payment_method: document.getElementById('pay_method')?.value || 'FATURADO',
            general_notes: document.getElementById('general_notes')?.value || '',
            
            origin_name: document.getElementById('orig_name')?.value || '',
            origin_street: document.getElementById('orig_street')?.value || '',
            origin_number: document.getElementById('orig_number')?.value || '',
            origin_district: document.getElementById('orig_district')?.value || '',
            origin_city: document.getElementById('orig_city')?.value || '',
            origin_zip_code: document.getElementById('orig_zip')?.value || '',
            origin_state: document.getElementById('orig_state')?.value || '',
            
            items: [],
            destinations: [],
            distributions: []
        };

        document.querySelectorAll('.item-card').forEach(card => {
            // Lógica para bloquear peso negativo e formatar
            let rawWeight = card.querySelector('.item-weight')?.value;
            let finalWeight = rawWeight ? Math.max(0, parseFloat(rawWeight)) : '';

            payload.items.push({
                id: card.dataset.id,
                description: card.querySelector('.item-desc')?.value || '',
                quantity: parseInt(card.querySelector('.item-qty')?.value || 1),
                type: card.querySelector('.item-type')?.value || '',
                weight: finalWeight,
                dimensions: card.querySelector('.item-dim')?.value || '',
                notes: card.querySelector('.item-notes')?.value || ''
            });
        });

        let hasDistributionError = false;

        document.querySelectorAll('.location-card').forEach(locCard => {
            const locId = locCard.dataset.id;
            
            // Lógica para bloquear valor negativo e formatar
            let rawValue = locCard.querySelector('.loc-value')?.value;
            let finalValue = rawValue ? Math.max(0, parseFloat(rawValue)) : 0.00;
            
            payload.destinations.push({
                id: locId,
                name: locCard.querySelector('.loc-name')?.value || '',
                phone: locCard.querySelector('.loc-phone')?.value || '',
                cep: locCard.querySelector('.loc-cep')?.value || '',
                street: locCard.querySelector('.loc-street')?.value || '',
                number: locCard.querySelector('.loc-num')?.value || '',
                complement: locCard.querySelector('.loc-comp')?.value || '',
                district: locCard.querySelector('.loc-dist')?.value || '',
                city: locCard.querySelector('.loc-city')?.value || '',
                state: locCard.querySelector('.loc-state')?.value || '',
                reference: locCard.querySelector('.loc-ref')?.value || '',
                value: finalValue
            });

            const checkedBoxes = locCard.querySelectorAll('.item-checkbox:checked');
            if (checkedBoxes.length === 0) {
                alert(`ERRO: O destino "${locCard.querySelector('.loc-name')?.value}" não tem nenhum item marcado para entrega!`);
                hasDistributionError = true;
            }

            checkedBoxes.forEach(chk => {
                const itemId = chk.value;
                const qtyInput = locCard.querySelector(`.qty-input-${itemId}`);
                
                payload.distributions.push({
                    item_id: itemId,
                    dest_id: locId,
                    quantity: parseInt(qtyInput?.value || 1)
                });
            });
        });

        if (hasDistributionError) return;

        for (let item of payload.items) {
            let totalDistribuido = payload.distributions
                .filter(d => d.item_id === item.id)
                .reduce((acc, curr) => acc + curr.quantity, 0);
            
            if (totalDistribuido > item.quantity) {
                alert(`ALERTA DE ESTOQUE: Você tentou entregar ${totalDistribuido}x "${item.description}", mas só informou ${item.quantity} nos itens!`);
                return;
            }
            if (totalDistribuido < item.quantity) {
                alert(`SOBRA DE PACOTE: Faltou vincular ${item.quantity - totalDistribuido} unidade(s) de "${item.description}" a um destino!`);
                return;
            }
        }

        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
        const btnSubmit = document.getElementById('btnSubmit');
        
        if (btnSubmit) {
            btnSubmit.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Processando...';
            btnSubmit.disabled = true;
        }

        const createUrl = OS_CREATE_CONFIG.createUrl || '/nova-os/';
        const dashboardUrl = OS_CREATE_CONFIG.dashboardUrl || '/painel-empresa/';

        fetch(createUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert('Tudo certo! OS Gerada com Sucesso: ' + data.os_number);
                window.location.href = dashboardUrl; 
            } else {
                alert('Erro do servidor: ' + data.message);
                if (btnSubmit) {
                    btnSubmit.innerHTML = '<i class="bi bi-send"></i> Gerar OS Oficial';
                    btnSubmit.disabled = false;
                }
            }
        })
        .catch(error => {
            console.error('Erro de Fetch:', error);
            alert('Erro de conexão com o servidor. Tente novamente.');
            if (btnSubmit) {
                btnSubmit.innerHTML = '<i class="bi bi-send"></i> Gerar OS Oficial';
                btnSubmit.disabled = false;
            }
        });

    } catch (erroInterno) {
        alert("Erro interno do painel: " + erroInterno.message);
        console.error(erroInterno);
    }
}