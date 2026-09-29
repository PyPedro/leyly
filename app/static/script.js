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
    const nome = document.getElementById('loginNome').value.trim();
    const whatsapp = document.getElementById('loginWhatsapp').value.trim();

    if (!nome || !whatsapp) {
        mostrarAviso("Preencha todos os campos para entrar.", "Atenção");
        return;
    }

    fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome, whatsapp })
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
    const nome = document.getElementById('cadNome').value.trim();
    const whatsapp = document.getElementById('cadWhatsapp').value.trim();

    if (!nome || !whatsapp) {
        mostrarAviso("Preencha os campos obrigatórios para criar sua conta.", "Atenção");
        return;
    }

    fetch('/api/cadastro', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome, whatsapp })
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
    
    produtoTemp = { id, nome, imagem, variantes, varianteSelecionada: 0, selecao: {} };
    document.getElementById('gradeNomeProduto').innerText = nome;

    const totalPecas = (variantes || []).reduce((total, variante) => {
        return total + (variante.tamanhos || []).reduce((soma, tamanho) => soma + Number(tamanho.estoque || 0), 0);
    }, 0);
    document.getElementById('gradeResumo').textContent = `${variantes.length} cores · ${totalPecas} peças`;

    const opcoesDeCor = document.getElementById('productColorChoices');
    opcoesDeCor.replaceChildren();
    variantes.forEach((variante, indice) => {
        const botao = document.createElement('button');
        botao.type = 'button';
        botao.className = `product-color-choice${indice === 0 ? ' active' : ''}`;
        botao.style.setProperty('--choice-color', variante.cor_hex || '#1c1c1a');
        const nomeCor = variante.cor_nome || variante.cor || 'Cor não definida';
        botao.setAttribute('aria-label', `Selecionar cor ${nomeCor}`);
        botao.setAttribute('aria-pressed', String(indice === 0));
        botao.title = nomeCor;
        const estoqueCor = (variante.tamanhos || []).reduce((total, tamanho, indiceTamanho) => {
            return total + Math.max(0, Number(tamanho.estoque || 0) - quantidadeNoCarrinho(variante, tamanho));
        }, 0);
        botao.innerHTML = `
            <span class="product-color-choice-main">
                <span class="product-color-choice-swatch" aria-hidden="true"></span>
                <span class="product-color-choice-label">${nomeCor}</span>
            </span>
            <span class="product-color-stock">${estoqueCor} un.</span>
        `;
        botao.addEventListener('click', () => selecionarCorProduto(indice));
        opcoesDeCor.appendChild(botao);
    });
    document.getElementById('gradeSelectedColor').textContent = variantes[0]?.cor_nome || variantes[0]?.cor || 'Cor não definida';
    renderizarTamanhosProduto();
    atualizarResumoGrade();

    document.getElementById('gradeModal').style.display = 'flex';
}

function selecionarCorProduto(indice) {
    produtoTemp.varianteSelecionada = indice;
    document.querySelectorAll('.product-color-choice').forEach((botao, index) => {
        const selecionado = index === indice;
        botao.classList.toggle('active', selecionado);
        botao.setAttribute('aria-pressed', String(selecionado));
    });
    const variante = produtoTemp.variantes[indice];
    document.getElementById('gradeSelectedColor').textContent = variante.cor_nome || variante.cor || 'Cor não definida';
    renderizarTamanhosProduto();
}

function renderizarTamanhosProduto() {
    const variante = produtoTemp.variantes[produtoTemp.varianteSelecionada];
    document.getElementById('productGradeRows').innerHTML = (variante.tamanhos || []).map((tamanho, indice) => {
        const chave = `${produtoTemp.varianteSelecionada}:${indice}`;
        const selecionada = Number(produtoTemp.selecao[chave] || 0);
        const emCarrinho = quantidadeNoCarrinho(variante, tamanho);
        const estoqueRestante = Math.max(0, Number(tamanho.estoque || 0) - emCarrinho);
        const semPreco = Number(tamanho.preco) <= 0;
        const indisponivel = estoqueRestante === 0 || semPreco;
        return `
        <div class="size-row">
            <div class="size-row-label">
                <span class="size-row-letter">${tamanho.nome}</span>
                <span class="size-row-details">
                    <span class="size-row-meta">${semPreco ? 'Preço pendente' : `R$ ${Number(tamanho.preco).toFixed(2).replace('.', ',')} / peça`}</span>
                    <span class="size-row-stock">Disponível: ${Math.max(0, estoqueRestante - selecionada)}</span>
                </span>
            </div>
            <div class="quantity-stepper" aria-label="Quantidade tamanho ${tamanho.nome}">
                <button type="button" class="quantity-stepper-button" aria-label="Diminuir tamanho ${tamanho.nome}" onclick="alterarQuantidadeGrade(${indice}, -1)" ${indisponivel || selecionada === 0 ? 'disabled' : ''}>−</button>
                <output id="gradeQuantity_${indice}" class="quantity-stepper-value" aria-live="polite">${selecionada}</output>
                <button type="button" class="quantity-stepper-button" aria-label="Aumentar tamanho ${tamanho.nome}" onclick="alterarQuantidadeGrade(${indice}, 1)" ${indisponivel || selecionada >= estoqueRestante ? 'disabled' : ''}>+</button>
            </div>
        </div>
    `;
    }).join('');
}

function quantidadeNoCarrinho(variante, tamanho) {
    const cartId = `${produtoTemp.id}_${variante.cor}_${tamanho.nome}`;
    return carrinho
        .filter(item => item.cartId === cartId)
        .reduce((total, item) => total + Number(item.quantidade || 0), 0);
}

function alterarQuantidadeGrade(indiceTamanho, delta) {
    const variante = produtoTemp.variantes[produtoTemp.varianteSelecionada];
    const tamanho = variante.tamanhos[indiceTamanho];
    const chave = `${produtoTemp.varianteSelecionada}:${indiceTamanho}`;
    const atual = Number(produtoTemp.selecao[chave] || 0);
    const maximo = Math.max(0, Number(tamanho.estoque || 0) - quantidadeNoCarrinho(variante, tamanho));
    produtoTemp.selecao[chave] = Math.min(maximo, Math.max(0, atual + delta));
    renderizarTamanhosProduto();
    atualizarResumoGrade();
}

function atualizarResumoGrade() {
    let pecas = 0;
    let totalCentavos = 0;
    Object.entries(produtoTemp.selecao).forEach(([chave, quantidade]) => {
        const [indiceVariante, indiceTamanho] = chave.split(':').map(Number);
        const tamanho = produtoTemp.variantes[indiceVariante]?.tamanhos?.[indiceTamanho];
        if (tamanho && quantidade > 0) {
            pecas += quantidade;
            totalCentavos += Math.round(Number(tamanho.preco) * 100) * quantidade;
        }
    });
    const total = (totalCentavos / 100).toFixed(2).replace('.', ',');
    document.getElementById('gradeSelectionSummary').textContent = `${pecas} ${pecas === 1 ? 'peça' : 'peças'} · R$ ${total}`;
    document.getElementById('gradeAddButton').disabled = pecas === 0;
}

function fecharModalGrade() {
    document.getElementById('gradeModal').style.display = 'none';
}

function confirmarGrade() {
    const itensSelecionados = [];
    Object.entries(produtoTemp.selecao).forEach(([chave, quantidade]) => {
        const [indiceVariante, indiceTamanho] = chave.split(':').map(Number);
        const variante = produtoTemp.variantes[indiceVariante];
        const tamanho = variante?.tamanhos?.[indiceTamanho];
        if (tamanho && quantidade > 0) itensSelecionados.push({ variante, tamanho, quantidade });
    });
    if (!itensSelecionados.length) return;

    for (const { variante, tamanho, quantidade } of itensSelecionados) {
        const disponivel = Math.max(0, Number(tamanho.estoque || 0) - quantidadeNoCarrinho(variante, tamanho));
        if (quantidade > disponivel) {
            mostrarAviso(`Estoque insuficiente para ${variante.cor || 'esta cor'}, tamanho ${tamanho.nome}. Restam ${disponivel} peças.`, 'Estoque atualizado');
            return;
        }
    }

    itensSelecionados.forEach(({ variante, tamanho, quantidade }) => {
        const cartId = `${produtoTemp.id}_${variante.cor}_${tamanho.nome}`;
        const itemExistente = carrinho.find(item => item.cartId === cartId);
        if (itemExistente) {
            itemExistente.quantidade += quantidade;
        } else {
            carrinho.push({
                cartId,
                id: produtoTemp.id,
                tamanho: tamanho.nome,
                cor: variante.cor,
                nome: produtoTemp.nome,
                preco: Number(tamanho.preco),
                quantidade,
                imagem: produtoTemp.imagem,
                estoqueMax: Number(tamanho.estoque),
            });
        }
    });

    fecharModalGrade();
    atualizarCarrinho();
    if (!document.getElementById('cartDrawer').classList.contains('open')) toggleCarrinho();
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

function atualizarProgressoMinimoAtacado(subtotal) {
    const valorMinimo = 330;
    const restante = Math.max(0, valorMinimo - subtotal);
    const percentual = Math.min(100, Math.max(0, subtotal / valorMinimo * 100));
    const barra = document.getElementById('wholesaleProgress');
    const progresso = document.getElementById('wholesaleMinimumProgress');
    const mensagem = document.getElementById('wholesaleMinimumRemaining');
    const resumo = document.querySelector('.wholesale-minimum');

    if (barra) barra.style.width = `${percentual}%`;
    if (progresso) progresso.setAttribute('aria-valuenow', String(Math.min(valorMinimo, Math.max(0, subtotal))));
    if (mensagem) {
        mensagem.textContent = restante > 0
            ? `Faltam R$ ${restante.toFixed(2).replace('.', ',')} para atingir o mínimo.`
            : 'Mínimo de atacado atingido.';
    }
    if (resumo) resumo.classList.toggle('is-complete', restante === 0);
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
        cartItemsContainer.classList.add('is-empty');
        cartItemsContainer.innerHTML = '<div class="empty-cart"><span class="empty-cart-icon" aria-hidden="true">+</span><strong>Seu pedido ainda está vazio</strong><p>Escolha os produtos e monte sua grade de atacado.</p><a class="empty-cart-link" href="#loja" onclick="toggleCarrinho()">Ver produtos</a></div>';
        if (cartSubtotal) cartSubtotal.innerText = 'R$ 0,00';
        if (cartDrawerTotal) cartDrawerTotal.innerText = 'R$ 0,00';
        atualizarProgressoMinimoAtacado(0);
    } else {
        cartItemsContainer.classList.remove('is-empty');
        let html = '';
        let subtotalCentavos = 0;

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
            
            subtotalCentavos += Math.round(Number(item.preco) * 100) * Number(item.quantidade);
        });

        // 2. Renderiza o HTML com os grupos e a grade compacta
        Object.values(produtosAgrupados).forEach(grupo => {
            html += `
                <div class="cart-item" style="margin-bottom: 15px; border-bottom: 1px solid var(--border-color); padding-bottom: 15px;">
                    <!-- Cabeçalho do Produto -->
                    <div style="display: flex; gap: 10px; align-items: flex-start;">
                        ${grupo.imagem ? `<img src="${grupo.imagem}" alt="${grupo.nome}" style="width: 55px; height: 55px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border-color);">` : '<div role="img" aria-label="Sem foto cadastrada" style="width:55px;height:55px;display:grid;place-items:center;background:#f0edf1;color:#777;font-size:9px;text-align:center;border-radius:6px;border:1px solid var(--border-color);">Sem foto</div>'}
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
        const subtotal = subtotalCentavos / 100;
        if (cartSubtotal) cartSubtotal.innerText = `R$ ${subtotal.toFixed(2).replace('.', ',')}`;
        atualizarProgressoMinimoAtacado(subtotal);

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
            const pesoKg = (Number(data.peso_gramas || 0) / 1000).toFixed(1).replace('.', ',');
            let html = `<div style="margin-top: 12px;"><strong style="font-size: 12px; color: #111; display: block; margin-bottom: 8px;">Estimativas de envio · origem ${data.cep_origem} · ${pesoKg} kg</strong><div style="display: flex; flex-direction: column; gap: 8px;">`;
            
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

    const subtotalAtual = carrinho.reduce((acc, item) => acc + Math.round(Number(item.preco) * 100) * Number(item.quantidade), 0) / 100;
    if (subtotalAtual < 330.00) {
        const falta = 330.00 - subtotalAtual;
        mostrarAviso(`Adicione mais <strong>R$ ${falta.toFixed(2).replace('.', ',')}</strong> em produtos para finalizar o pedido.`, "Pedido incompleto");
        return;
    }

    const btnCheckout = document.querySelector('.btn-checkout');
    if (btnCheckout) {
        btnCheckout.innerText = 'Preparando pedido...';
        btnCheckout.disabled = true;
    }
    const janelaWhatsApp = window.open('about:blank', '_blank');

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
            if (janelaWhatsApp) {
                janelaWhatsApp.location.href = data.url_whatsapp;
            } else {
                window.location.href = data.url_whatsapp;
                return;
            }
            mostrarAviso('Seu pedido está pronto no WhatsApp da loja. Toque em enviar para concluir a solicitação.', 'Pedido no WhatsApp');
            if (btnCheckout) {
                btnCheckout.innerText = 'Finalizar Pedido';
                btnCheckout.disabled = false;
            }
        } else {
            janelaWhatsApp?.close();
            mostrarAviso(data.mensagem || 'Não foi possível concluir o pedido.', 'Atenção');
            if (btnCheckout) {
                btnCheckout.innerText = 'Finalizar Pedido';
                btnCheckout.disabled = false;
            }
        }
    })
    .catch(error => {
        janelaWhatsApp?.close();
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

let buscaProdutosTimer = null;
let buscaProdutosController = null;

function filtrarProdutos() {
    const termo = document.getElementById('searchInput').value.trim();
    const feedback = document.getElementById('searchFeedback');
    const resultados = document.getElementById('searchResults');
    window.clearTimeout(buscaProdutosTimer);
    buscaProdutosController?.abort();
    resultados?.replaceChildren();

    if (termo.length < 2) {
        feedback.textContent = 'Digite ao menos 2 caracteres para buscar no catálogo.';
        return;
    }

    feedback.textContent = 'Buscando em todos os produtos...';
    buscaProdutosTimer = window.setTimeout(async () => {
        buscaProdutosController = new AbortController();
        try {
            const resposta = await fetch(`/api/produtos/buscar?q=${encodeURIComponent(termo)}`, {
                signal: buscaProdutosController.signal,
            });
            if (!resposta.ok) throw new Error('Falha ao buscar produtos.');
            const produtos = await resposta.json();
            if (!resultados || !feedback) return;

            produtos.forEach(produto => {
                const botao = document.createElement('button');
                botao.type = 'button';
                botao.className = 'catalog-search-result';
                botao.setAttribute('role', 'listitem');
                botao.setAttribute('aria-label', `Selecionar ${produto.nome}, referência ${produto.codigo}`);

                const imagem = document.createElement('img');
                imagem.className = 'catalog-search-image';
                imagem.alt = '';
                imagem.loading = 'lazy';
                if (produto.imagem_url) imagem.src = produto.imagem_url;
                else imagem.hidden = true;

                const texto = document.createElement('span');
                texto.className = 'catalog-search-copy';
                const nome = document.createElement('strong');
                nome.className = 'catalog-search-name';
                nome.textContent = produto.nome;
                const referencia = document.createElement('span');
                referencia.className = 'catalog-search-meta';
                referencia.textContent = `Ref: ${produto.codigo}`;
                texto.append(nome, referencia);

                const preco = document.createElement('span');
                preco.className = 'catalog-search-price';
                preco.textContent = produto.preco_minimo > 0
                    ? `A partir de R$ ${Number(produto.preco_minimo).toFixed(2).replace('.', ',')}`
                    : 'Preço pendente';

                botao.append(imagem, texto, preco);
                botao.addEventListener('click', () => {
                    fecharBuscaModal();
                    abrirModalGrade(produto.id, produto.nome, produto.variantes, produto.imagem_url);
                });
                resultados.appendChild(botao);
            });

            feedback.textContent = produtos.length
                ? `${produtos.length} produto(s) encontrado(s) em todo o catálogo.`
                : `Nenhum produto encontrado para "${termo}".`;
        } catch (erro) {
            if (erro.name !== 'AbortError' && feedback) feedback.textContent = erro.message || 'Erro ao buscar produtos.';
        }
    }, 180);
}

function atualizarControlesCarrosselPromocoes() {
    const trilha = document.getElementById('promotion-carousel-track');
    const anterior = document.getElementById('promotion-carousel-prev');
    const proxima = document.getElementById('promotion-carousel-next');
    if (!trilha) return;

    const maximo = Math.max(0, trilha.scrollWidth - trilha.clientWidth);
    const haRolagem = maximo > 1;
    if (anterior) {
        anterior.hidden = !haRolagem;
        anterior.disabled = !haRolagem || trilha.scrollLeft <= 1;
    }
    if (proxima) {
        proxima.hidden = !haRolagem;
        proxima.disabled = !haRolagem || trilha.scrollLeft >= maximo - 1;
    }
}

function inicializarCarrosselPromocoes() {
    const trilha = document.getElementById('promotion-carousel-track');
    if (!trilha) return;

    const anterior = document.getElementById('promotion-carousel-prev');
    const proxima = document.getElementById('promotion-carousel-next');
    const mover = direcao => {
        const primeiroCard = trilha.querySelector('.promotion-carousel-slide:not([hidden])');
        const gap = Number.parseFloat(getComputedStyle(trilha).columnGap) || 0;
        const passo = primeiroCard ? primeiroCard.getBoundingClientRect().width + gap : trilha.clientWidth;
        const maximo = Math.max(0, trilha.scrollWidth - trilha.clientWidth);
        const proximaPosicao = Math.max(0, Math.min(maximo, trilha.scrollLeft + direcao * passo));
        trilha.scrollTo({ left: proximaPosicao, behavior: 'instant' });
        atualizarControlesCarrosselPromocoes();
    };

    anterior?.addEventListener('click', () => mover(-1));
    proxima?.addEventListener('click', () => mover(1));
    trilha.addEventListener('scroll', () => requestAnimationFrame(atualizarControlesCarrosselPromocoes), { passive: true });
    window.addEventListener('resize', atualizarControlesCarrosselPromocoes);
    requestAnimationFrame(atualizarControlesCarrosselPromocoes);
}

function inicializarCarrosselBanner() {
    const banner = document.getElementById('inicio');
    const slides = Array.from(banner?.querySelectorAll('.hero-slide') || []);
    const pontos = Array.from(banner?.querySelectorAll('.hero-carousel-dot') || []);
    if (slides.length < 2) return;

    let indiceAtual = 0;
    let pausado = false;
    const mostrarSlide = indice => {
        indiceAtual = (indice + slides.length) % slides.length;
        slides.forEach((slide, posicao) => {
            const ativo = posicao === indiceAtual;
            slide.classList.toggle('is-active', ativo);
            slide.setAttribute('aria-hidden', String(!ativo));
        });
        pontos.forEach((ponto, posicao) => {
            const ativo = posicao === indiceAtual;
            ponto.classList.toggle('is-active', ativo);
            ponto.setAttribute('aria-current', String(ativo));
        });
    };

    banner.querySelectorAll('[data-hero-direction]').forEach(botao => {
        botao.addEventListener('click', () => mostrarSlide(indiceAtual + Number(botao.dataset.heroDirection)));
    });
    pontos.forEach((ponto, indice) => ponto.addEventListener('click', () => mostrarSlide(indice)));
    banner.addEventListener('mouseenter', () => { pausado = true; });
    banner.addEventListener('mouseleave', () => { pausado = false; });
    banner.addEventListener('focusin', () => { pausado = true; });
    banner.addEventListener('focusout', evento => {
        if (!banner.contains(evento.relatedTarget)) pausado = false;
    });

    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        window.setInterval(() => {
            if (!pausado && !document.hidden) mostrarSlide(indiceAtual + 1);
        }, 5000);
    }
}

inicializarCarrosselPromocoes();
inicializarCarrosselBanner();

document.addEventListener('keydown', function(event) {
    if (event.key === "Escape" || event.key === "Enter") {
        fecharBuscaModal();
    }
});