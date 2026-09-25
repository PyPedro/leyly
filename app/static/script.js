let carrinho = [];
let freteSelecionadoValor = 0;
let produtoTemp = null;

function trocarImagemProduto(botao, imagemUrl) {
    const galeria = botao.closest('.product-gallery');
    const imagemPrincipal = galeria ? galeria.querySelector('.product-main-image') : null;
    if (!imagemPrincipal) return;
    const requisicao = Number(galeria.dataset.imageRequest || 0) + 1;
    galeria.dataset.imageRequest = requisicao;
    const imagemPreparada = new Image();
    imagemPreparada.src = imagemUrl;
    imagemPreparada.decode().then(() => {
        if (Number(galeria.dataset.imageRequest) === requisicao) imagemPrincipal.src = imagemUrl;
    }).catch(() => {
        if (Number(galeria.dataset.imageRequest) === requisicao) imagemPrincipal.src = imagemUrl;
    });
    const miniaturas = Array.from(galeria.querySelectorAll('.product-thumbnail'));
    miniaturas.forEach(thumbnail => {
        thumbnail.classList.remove('active');
        thumbnail.setAttribute('aria-selected', 'false');
    });
    botao.classList.add('active');
    botao.setAttribute('aria-selected', 'true');
    const contador = galeria.querySelector('.gallery-counter');
    if (contador) contador.textContent = `${miniaturas.indexOf(botao) + 1} / ${miniaturas.length}`;
}

function precarregarImagemGaleria(botao, direcao = 0) {
    const galeria = botao.closest('.product-gallery');
    if (!galeria) return;
    const miniaturas = Array.from(galeria.querySelectorAll('.product-thumbnail'));
    let alvo = botao;
    if (direcao) {
        const atual = miniaturas.findIndex(miniatura => miniatura.classList.contains('active'));
        alvo = miniaturas[(atual + direcao + miniaturas.length) % miniaturas.length];
    }
    if (!alvo || alvo.dataset.preloaded) return;
    alvo.dataset.preloaded = 'true';
    const imagem = new Image();
    imagem.src = alvo.dataset.gallerySrc;
}

function navegarGaleria(botao, direcao) {
    const galeria = botao.closest('.product-gallery');
    if (!galeria) return;
    const miniaturas = Array.from(galeria.querySelectorAll('.product-thumbnail'));
    const atual = miniaturas.findIndex(miniatura => miniatura.classList.contains('active'));
    const proximo = (atual + direcao + miniaturas.length) % miniaturas.length;
    const miniatura = miniaturas[proximo];
    trocarImagemProduto(miniatura, miniatura.dataset.gallerySrc);
    miniatura.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
}

// ==========================================
// FUNÇÕES DE ALERTAS (MODAL CUSTOMIZADO)
// ==========================================
function mostrarAviso(mensagem, titulo = "Aviso Fitness Club") {
    const modal = document.getElementById('customModal');
    const msgElement = document.getElementById('modalMensagem');
    const tituloElement = document.getElementById('modalTitulo');
    
    if (modal && msgElement && tituloElement) {
        tituloElement.innerText = titulo;
        msgElement.innerHTML = mensagem.replace(/\n/g, '<br>');
        modal.style.display = 'flex';
    } else {
        alert(mensagem);
    }
}

function fecharModalCustom() {
    const modal = document.getElementById('customModal');
    if (modal) modal.style.display = 'none';
}

// ==========================================
// FUNÇÕES DE AUTENTICAÇÃO E LOGIN
// ==========================================
function abrirAuthModal() {
    const modal = document.getElementById('authModal');
    if (modal) modal.style.display = 'flex';
}

function fecharAuthModal() {
    const modal = document.getElementById('authModal');
    if (modal) modal.style.display = 'none';
}

function alternarAbaAuth(aba) {
    const formLogin = document.getElementById('formLogin');
    const formCadastro = document.getElementById('formCadastro');
    const btnLogin = document.getElementById('tabLoginBtn');
    const btnCadastro = document.getElementById('tabCadastroBtn');

    if (aba === 'login') {
        formLogin.style.display = 'block';
        formCadastro.style.display = 'none';
        btnLogin.style.color = 'var(--brand-purple)';
        btnLogin.style.borderBottom = '2px solid var(--brand-purple)';
        btnCadastro.style.color = '#888';
        btnCadastro.style.borderBottom = 'none';
    } else {
        formLogin.style.display = 'none';
        formCadastro.style.display = 'block';
        btnCadastro.style.color = 'var(--brand-purple)';
        btnCadastro.style.borderBottom = '2px solid var(--brand-purple)';
        btnLogin.style.color = '#888';
        btnLogin.style.borderBottom = 'none';
    }
}

function fazerLogin() {
    const email = document.getElementById('loginEmail').value;
    const senha = document.getElementById('loginSenha').value;

    if (!email || !senha) {
        mostrarAviso("Preencha todos os campos para entrar.", "Atenção");
        return;
    }

    fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, senha })
    })
    .then(res => res.json())
    .then(data => {
        if (data.sucesso) {
            window.location.reload();
        } else {
            mostrarAviso(data.mensagem, "Erro no Login");
        }
    });
}

function fazerCadastro() {
    const nome = document.getElementById('cadNome').value;
    const email = document.getElementById('cadEmail').value;
    const whatsapp = document.getElementById('cadWhatsapp').value;
    const senha = document.getElementById('cadSenha').value;

    if (!nome || !email || !senha) {
        mostrarAviso("Preencha os campos obrigatórios para criar sua conta.", "Atenção");
        return;
    }

    fetch('/api/cadastro', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome, email, senha, whatsapp })
    })
    .then(res => res.json())
    .then(data => {
        if (data.sucesso) {
            window.location.reload();
        } else {
            mostrarAviso(data.mensagem, "Erro no Cadastro");
        }
    });
}

// ==========================================
// CARRINHO E GRADE DE TAMANHOS
// ==========================================
function tentarAbrirCarrinho() {
    if (!usuarioLogado) {
        mostrarAviso("Para acessar seu pedido e cotar frete, é necessário fazer cadastro ou entrar na sua conta.", "Área Restrita a Lojistas");
        abrirAuthModal();
        return;
    }
    toggleCarrinho();
}

function toggleCarrinho() {
    if (!usuarioLogado) {
        abrirAuthModal();
        return;
    }
    const drawer = document.getElementById('cartDrawer');
    const overlay = document.getElementById('cartOverlay');
    if (drawer && overlay) {
        drawer.classList.toggle('open');
        overlay.classList.toggle('open');
    }
}

function abrirModalGrade(id, nome, variantes, imagem) {
    if (!usuarioLogado) { 
        mostrarAviso("Faça login ou cadastre-se para montar seu pedido de atacado.", "Acesso Lojista"); 
        abrirAuthModal(); 
        return; 
    }
    
    produtoTemp = { id, nome, imagem, variantes, varianteSelecionada: 0 };
    document.getElementById('gradeNomeProduto').innerText = nome;
    document.getElementById('productColorChoices').innerHTML = variantes.map((variante, indice) => `<button type="button" class="product-color-choice${indice === 0 ? ' active' : ''}" style="--choice-color: ${variante.cor || '#1c1c1a'}" aria-label="Selecionar cor" onclick="selecionarCorProduto(${indice})"></button>`).join('');
    renderizarTamanhosProduto();

    document.getElementById('gradeModal').style.display = 'flex';
}

function selecionarCorProduto(indice) {
    produtoTemp.varianteSelecionada = indice;
    document.querySelectorAll('.product-color-choice').forEach((botao, index) => botao.classList.toggle('active', index === indice));
    renderizarTamanhosProduto();
}

function renderizarTamanhosProduto() {
    const variante = produtoTemp.variantes[produtoTemp.varianteSelecionada];
    document.getElementById('productGradeRows').innerHTML = variante.tamanhos.map((tamanho, indice) => `<div class="size-row"><span class="size-label">${tamanho.nome}</span><span class="size-stock">Disp: ${tamanho.estoque} · R$ ${Number(tamanho.preco).toFixed(2).replace('.', ',')}</span><input type="number" id="inputGrade_${indice}" class="size-input" min="0" max="${tamanho.estoque}" value="0" ${tamanho.estoque === 0 ? 'disabled' : ''}></div>`).join('');
}

function fecharModalGrade() {
    document.getElementById('gradeModal').style.display = 'none';
}

function confirmarGrade() {
    let qtdeTotal = 0;
    
    const variante = produtoTemp.variantes[produtoTemp.varianteSelecionada];
    variante.tamanhos.forEach((tamanho, indice) => {
        let qtdeInput = parseInt(document.getElementById('inputGrade_' + indice).value) || 0;
        
        if (qtdeInput > 0) {
            let maxEstoque = Number(tamanho.estoque);
            let cartId = produtoTemp.id + '_' + variante.cor + '_' + tamanho.nome; 
            
            let itemExistente = carrinho.find(i => i.cartId === cartId);
            let qtdeNoCarrinho = itemExistente ? itemExistente.quantidade : 0;
            
            if (qtdeNoCarrinho + qtdeInput > maxEstoque) {
                mostrarAviso(`Estoque insuficiente para o tamanho ${tamanho.nome}. Você já tem ${qtdeNoCarrinho} na sacola e restam apenas ${maxEstoque} na fábrica.`, "Limite de Grade");
                return;
            }

            if (itemExistente) {
                itemExistente.quantidade += qtdeInput;
            } else {
                carrinho.push({
                    cartId: cartId,
                    id: produtoTemp.id,
                    tamanho: tamanho.nome,
                    cor: variante.cor,
                    nome: produtoTemp.nome,
                    preco: parseFloat(tamanho.preco),
                    quantidade: qtdeInput,
                    imagem: produtoTemp.imagem,
                    estoqueMax: maxEstoque
                });
            }
            qtdeTotal += qtdeInput;
        }
    });

    if (qtdeTotal > 0) {
        fecharModalGrade();
        atualizarCarrinho();
        if (!document.getElementById('cartDrawer').classList.contains('open')) toggleCarrinho();
    } else {
        mostrarAviso("Selecione a quantidade de pelo menos 1 tamanho para adicionar à sacola.", "Atenção");
    }
}

function alterarQuantidade(cartId, delta) {
    const item = carrinho.find(i => i.cartId === cartId);
    if (item) {
        const novaQtd = item.quantidade + delta;
        if (novaQtd > item.estoqueMax) {
            mostrarAviso(`Estoque insuficiente no tamanho ${item.tamanho}. Restam apenas ${item.estoqueMax} peças.`, "Limite de Estoque");
            return;
        }
        item.quantidade = novaQtd;
        if (item.quantidade <= 0) {
            carrinho = carrinho.filter(i => i.cartId !== cartId);
        }
    }
    atualizarCarrinho();
}

function atualizarCarrinho() {
    const cartItemsContainer = document.getElementById('cartItems');
    const cartCount = document.getElementById('cartCount');
    const cartSubtotal = document.getElementById('cartSubtotal');
    const cartDrawerTotal = document.getElementById('cartDrawerTotal');

    if (!cartItemsContainer) return;

    const totalItensCount = carrinho.reduce((acc, item) => acc + item.quantidade, 0);
    if (cartCount) cartCount.innerText = totalItensCount;

    if (carrinho.length === 0) {
        cartItemsContainer.innerHTML = '<p class="empty-cart">Seu pedido está vazio.</p>';
        if (cartSubtotal) cartSubtotal.innerText = 'R$ 0,00';
        if (cartDrawerTotal) cartDrawerTotal.innerText = 'R$ 0,00';
    } else {
        let html = '';
        let subtotal = 0;

        // 1. Agrupa os itens do carrinho pelo ID do Produto (Junta os tamanhos)
        const produtosAgrupados = {};
        
        carrinho.forEach(item => {
            if (!produtosAgrupados[item.id]) {
                produtosAgrupados[item.id] = {
                    id: item.id,
                    nome: item.nome,
                    imagem: item.imagem,
                    preco: item.preco,
                    tamanhos: [],
                    totalValor: 0,
                    totalPecas: 0
                };
            }
            produtosAgrupados[item.id].tamanhos.push(item);
            produtosAgrupados[item.id].totalValor += (item.preco * item.quantidade);
            produtosAgrupados[item.id].totalPecas += item.quantidade;
            
            subtotal += (item.preco * item.quantidade);
        });

        // 2. Renderiza o HTML com os grupos e a grade compacta
        Object.values(produtosAgrupados).forEach(grupo => {
            html += `
                <div class="cart-item" style="margin-bottom: 15px; border-bottom: 1px solid var(--border-color); padding-bottom: 15px;">
                    <!-- Cabeçalho do Produto -->
                    <div style="display: flex; gap: 10px; align-items: flex-start;">
                        <img src="${grupo.imagem}" alt="${grupo.nome}" style="width: 55px; height: 55px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border-color);">
                        <div style="flex-grow: 1;">
                            <h4 style="font-size: 12px; margin: 0 0 4px 0; color: #111; line-height: 1.3;">${grupo.nome}</h4>
                            <span style="font-size: 11px; color: #666;">${grupo.tamanhos.map(t => `${t.tamanho}: R$ ${t.preco.toFixed(2).replace('.', ',')}`).join(' · ')}</span>
                        </div>
                        <div style="text-align: right;">
                            <strong style="font-size: 13px; color: var(--brand-purple);">R$ ${grupo.totalValor.toFixed(2).replace('.', ',')}</strong>
                            <div style="font-size: 10px; color: #888; font-weight: 700; margin-top: 3px; text-transform: uppercase;">${grupo.totalPecas} Peça(s)</div>
                        </div>
                    </div>
                    
                    <!-- Grade de Tamanhos Interna (Em uma única linha compacta) -->
                    <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; background: #f8fafc; border-radius: 6px; padding: 8px; border: 1px solid #e2e8f0;">
                        ${grupo.tamanhos.map(t => `
                            <div style="display: flex; align-items: center; gap: 5px; background: #ffffff; padding: 3px 6px; border-radius: 4px; border: 1px solid #cbd5e1; box-shadow: 0 1px 2px rgba(0,0,0,0.02);">
                                <span class="cart-color-dot" style="background:${t.cor || '#1c1c1a'}" title="Cor selecionada"></span><span style="font-size: 11px; font-weight: 800; color: var(--brand-purple); min-width: 16px; text-align: center;">${t.tamanho}</span>
                                <button onclick="alterarQuantidade('${t.cartId}', -1)" style="width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; background: #e2e8f0; color: #475569; border: none; cursor: pointer; border-radius: 3px; font-weight: bold; transition: 0.2s;" onmouseover="this.style.background='#cbd5e1'" onmouseout="this.style.background='#e2e8f0'">-</button>
                                <span style="font-size: 12px; font-weight: 700; color: #0f172a; min-width: 14px; text-align: center;">${t.quantidade}</span>
                                <button onclick="alterarQuantidade('${t.cartId}', 1)" style="width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; background: #e2e8f0; color: #475569; border: none; cursor: pointer; border-radius: 3px; font-weight: bold; transition: 0.2s;" onmouseover="this.style.background='#cbd5e1'" onmouseout="this.style.background='#e2e8f0'">+</button>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        });

        cartItemsContainer.innerHTML = html;
        if (cartSubtotal) cartSubtotal.innerText = `R$ ${subtotal.toFixed(2).replace('.', ',')}`;

        const totalFinal = subtotal + freteSelecionadoValor;
        if (cartDrawerTotal) cartDrawerTotal.innerText = `R$ ${totalFinal.toFixed(2).replace('.', ',')}`;
    }

    let radioFrete = document.querySelector('input[name="opcaoFrete"]:checked');
    let tipoFrete = radioFrete ? radioFrete.getAttribute('data-tipo') : 'Não selecionado';

    if (usuarioLogado) {
        fetch('/api/carrinho/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                carrinho: carrinho, 
                frete: freteSelecionadoValor, 
                frete_tipo: tipoFrete 
            })
        }).catch(err => console.log("Sincronizando em background..."));
    }
}

// ==========================================
// FRETE E CHECKOUT
// ==========================================
function calcularFrete() {
    const cepInput = document.getElementById('cepInput');
    const freteResultado = document.getElementById('freteResultado');
    
    if (!cepInput || !freteResultado) return;
    
    const cep = cepInput.value.replace(/\D/g, '');

    if (cep.length !== 8) {
        freteResultado.innerHTML = '<span style="color: red; font-size: 11px; display: block; margin-top: 8px;">Digite um CEP válido com 8 dígitos.</span>';
        return;
    }

    freteResultado.innerHTML = '<span style="color: #666; font-size: 11px; display: block; margin-top: 8px;">Calculando opções de frete...</span>';

    fetch('/calcular-frete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cep: cep, carrinho: carrinho })
    })
    .then(response => response.json())
    .then(data => {
        if (data.sucesso) {
            let html = '<div style="margin-top: 12px;"><strong style="font-size: 12px; color: #111; display: block; margin-bottom: 8px;">Opções de Envio Disponíveis:</strong><div style="display: flex; flex-direction: column; gap: 8px;">';
            
            data.opcoes.forEach(opcao => {
                const isExcursao = opcao.transportadora === 'Excursão';
                const valorTexto = isExcursao ? 'A combinar' : `R$ ${opcao.valor.toFixed(2).replace('.', ',')}`;
                
                html += `
                    <label style="display: flex; align-items: center; justify-content: space-between; background: #faf8f5; padding: 10px 12px; border-radius: 8px; border: 1px solid #e5e0d8; cursor: pointer;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <input type="radio" name="opcaoFrete" value="${opcao.valor}" data-tipo="${opcao.transportadora}" onchange="selecionarFrete(${opcao.valor}, '${opcao.transportadora}')" style="accent-color: #000; cursor: pointer;">
                            <div>
                                <span style="font-size: 12px; font-weight: 600; color: #111; display: block;">${opcao.transportadora} <span style="font-weight: 400; color: #666;">(${opcao.nome})</span></span>
                                <span style="font-size: 10px; color: #777;">Prazo: ${opcao.prazo}</span>
                            </div>
                        </div>
                        <strong style="font-size: 12px; color: #000;">${valorTexto}</strong>
                    </label>
                `;
            });
            
            html += '</div>';
            html += '<div id="excursaoAvisoBox" style="display: none; margin-top: 10px; background: #fff3cd; border: 1px solid #ffeeba; color: #856404; padding: 10px; border-radius: 6px; font-size: 11px; line-height: 1.4;"></div>';
            html += '</div>';
            
            freteResultado.innerHTML = html;
        } else {
            freteResultado.innerHTML = `<span style="color: red; font-size: 11px; display: block; margin-top: 8px;">${data.mensagem}</span>`;
        }
    })
    .catch(error => {
        freteResultado.innerHTML = '<span style="color: red; font-size: 11px; display: block; margin-top: 8px;">Erro ao calcular o frete.</span>';
    });
}

function selecionarFrete(valor, tipoTransportadora) {
    freteSelecionadoValor = parseFloat(valor);
    const rowFrete = document.getElementById('rowFrete');
    const cartFreteValue = document.getElementById('cartFreteValue');
    const excursaoBox = document.getElementById('excursaoAvisoBox');

    if (rowFrete && cartFreteValue) {
        rowFrete.style.display = 'flex';
        if (tipoTransportadora === 'Excursão') {
            cartFreteValue.innerText = 'A combinar';
            if (excursaoBox) {
                excursaoBox.style.display = 'block';
                excursaoBox.innerHTML = '<strong>Como funciona o frete por excursão?</strong><br>Ao selecionar esta opção, fique tranquilo(a): Entraremos em contato e o valor do frete será tratado diretamente entre você e a excursão após a conclusão do seu pedido. O tipo de frete neste caso pode ser alterado após a finalização da compra.';
            }
        } else {
            cartFreteValue.innerText = `R$ ${freteSelecionadoValor.toFixed(2).replace('.', ',')}`;
            if (excursaoBox) {
                excursaoBox.style.display = 'none';
            }
        }
    }
    atualizarCarrinho();
}

function finalizarPedido() {
    if (carrinho.length === 0) {
        mostrarAviso('Seu carrinho está vazio.', 'Carrinho Vazio');
        return;
    }

    const subtotalAtual = carrinho.reduce((acc, item) => acc + (item.preco * item.quantidade), 0);
    if (subtotalAtual < 330.00) {
        const falta = 330.00 - subtotalAtual;
        mostrarAviso(`Adicione mais <strong>R$ ${falta.toFixed(2).replace('.', ',')}</strong> em produtos para finalizar o pedido.`, "Pedido incompleto");
        return;
    }

    const btnCheckout = document.querySelector('.btn-checkout');
    if (btnCheckout) {
        btnCheckout.innerText = 'Validando pedido...';
        btnCheckout.disabled = true;
    }

    fetch('/checkout-infinitepay', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            carrinho: carrinho, 
            frete: freteSelecionadoValor 
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.sucesso && data.url_whatsapp) {
            window.open(data.url_whatsapp, '_blank');
            mostrarAviso('Resumo enviado para o WhatsApp da loja. Aguarde o atendimento para confirmar o pedido.', 'Cliente especial');
            if (btnCheckout) {
                btnCheckout.innerText = 'Finalizar Pedido';
                btnCheckout.disabled = false;
            }
        } else if (data.sucesso && data.url_pagamento) {
            window.location.href = data.url_pagamento;
        } else {
            mostrarAviso(data.mensagem || 'Não foi possível concluir o pedido.', 'Atenção');
            if (btnCheckout) {
                btnCheckout.innerText = 'Finalizar Pedido';
                btnCheckout.disabled = false;
            }
        }
    })
    .catch(error => {
        mostrarAviso('Erro de conexão ao processar o pedido.', 'Erro de Conexão');
        if (btnCheckout) {
            btnCheckout.innerText = 'Finalizar Pedido';
            btnCheckout.disabled = false;
        }
    });
}

// ==========================================
// SISTEMA DE BUSCA EM TEMPO REAL
// ==========================================
function abrirBuscaModal() {
    const modal = document.getElementById('searchModal');
    if (modal) {
        modal.style.display = 'flex';
        setTimeout(() => document.getElementById('searchInput').focus(), 100);
        
        const lojaSecao = document.getElementById('loja');
        const headerHeight = document.querySelector('.main-header').offsetHeight;
        window.scrollTo({
            top: lojaSecao.getBoundingClientRect().top + window.scrollY - headerHeight - 20,
            behavior: 'smooth'
        });
    }
}

function fecharBuscaModal() {
    const modal = document.getElementById('searchModal');
    if (modal) modal.style.display = 'none';
}

function filtrarProdutos() {
    const termo = document.getElementById('searchInput').value.toLowerCase().trim();
    const cards = document.querySelectorAll('.product-card');
    const feedback = document.getElementById('searchFeedback');
    
    let produtosEncontrados = 0;

    cards.forEach(card => {
        const nomeProduto = card.querySelector('.product-name').innerText.toLowerCase();
        
        if (nomeProduto.includes(termo)) {
            card.style.display = 'flex';
            produtosEncontrados++;
        } else {
            card.style.display = 'none';
        }
    });

    if (feedback) {
        feedback.style.display = 'block';
        if (produtosEncontrados === 0) {
            feedback.innerHTML = `<span style="color: red;">Nenhum produto encontrado para "${termo}".</span>`;
        } else {
            feedback.innerHTML = `Mostrando ${produtosEncontrados} produto(s).`;
        }
    }
}

document.addEventListener('keydown', function(event) {
    if (event.key === "Escape" || event.key === "Enter") {
        fecharBuscaModal();
    }
});