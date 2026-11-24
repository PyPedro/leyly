let carrinho = [];
const CHAVE_CARRINHO_LOCAL = 'leyly_carrinho';
const CHAVE_RETOMADA_CHECKOUT = 'leyly_checkout_pendente';
let pedidoAtualId = null;
let carrinhoLocalDisponivel = false;
const fretesValidos = ['Correios', 'Excursão', 'Retirada em Surubim'];
let freteSelecionadoValor = 0;
let freteSelecionadoTipo = 'Não selecionado';
let produtoTemp = null;
let carrinhoInicializado = false;
let carrinhoReservadoNoInicio = false;
let reservaInicialCarrinho = [];
let observacaoPedido = '';
let temporizadorObservacaoPedido = null;
let temporizadorStatusPix = null;
let pedidoPixMonitoradoId = null;
let acompanhamentoPixAtivo = false;
let checkoutProcessando = false;
let checkoutConcluido = false;
let sincronizacaoCarrinhoPendente = Promise.resolve();
const DDDS_BRASIL = new Set([
    '11', '12', '13', '14', '15', '16', '17', '18', '19',
    '21', '22', '24', '27', '28',
    '31', '32', '33', '34', '35', '37', '38',
    '41', '42', '43', '44', '45', '46', '47', '48', '49',
    '51', '53', '54', '55',
    '61', '62', '63', '64', '65', '66', '67', '68', '69',
    '71', '73', '74', '75', '77', '79',
    '81', '82', '83', '84', '85', '86', '87', '88', '89',
    '91', '92', '93', '94', '95', '96', '97', '98', '99',
]);
let nomeClienteAtual = identificacaoClienteInicial.nome || '';
let whatsappClienteAtual = String(identificacaoClienteInicial.whatsapp || '').replace(/\D/g, '');
let itensPendentesIdentificacao = null;

function telefoneClienteValido(valor) {
    const digitos = String(valor || '').replace(/\D/g, '');
    return digitos.length === 11 && DDDS_BRASIL.has(digitos.slice(0, 2)) && digitos[2] === '9';
}

function formatarTelefoneCliente(valor) {
    const digitos = String(valor || '').replace(/\D/g, '').slice(0, 11);
    if (!digitos.length) return '';
    let formatado = digitos.length >= 2 ? `(${digitos.slice(0, 2)})` : `(${digitos}`;
    if (digitos.length > 2) formatado += ` ${digitos[2]}`;
    if (digitos.length > 3) formatado += ` ${digitos.slice(3, 7)}`;
    if (digitos.length > 7) formatado += `-${digitos.slice(7, 11)}`;
    return formatado;
}

function aplicarMascaraTelefone(evento) {
    evento.target.value = formatarTelefoneCliente(evento.target.value);
}

function clienteIdentificado() {
    return nomeClienteAtual.trim().length >= 2 && telefoneClienteValido(whatsappClienteAtual);
}

function mesmaVariacaoCarrinho(itemA, itemB) {
    return String(itemA.id) === String(itemB.id)
        && String(itemA.cor || '').trim().toLocaleLowerCase() === String(itemB.cor || '').trim().toLocaleLowerCase()
        && String(itemA.tamanho || '').trim().toLocaleLowerCase() === String(itemB.tamanho || '').trim().toLocaleLowerCase();
}

function mesclarCarrinhos(itensConta, itensConvidado) {
    const itensMesclados = itensConta.map(item => ({ ...item }));
    itensConvidado.forEach(itemConvidado => {
        const itemExistente = itensMesclados.find(item => mesmaVariacaoCarrinho(item, itemConvidado));
        if (itemExistente) {
            itemExistente.quantidade = Number(itemExistente.quantidade || 0) + Number(itemConvidado.quantidade || 0);
        } else {
            itensMesclados.push({ ...itemConvidado });
        }
    });
    return itensMesclados;
}

function salvarRetomadaCheckout() {
    try {
        sessionStorage.setItem(CHAVE_RETOMADA_CHECKOUT, JSON.stringify({
            frete_tipo: freteSelecionadoTipo,
            forma_pagamento: document.querySelector('input[name="metodoPagamento"]:checked')?.value || 'pix',
            observacao: observacaoPedido,
        }));
        return true;
    } catch (erro) {
        console.error('Não foi possível salvar a retomada do checkout:', erro);
        mostrarAviso('Não foi possível preservar a continuação do pedido neste navegador. Tente novamente antes de entrar ou cadastrar-se.', 'Não foi possível continuar');
        return false;
    }
}

function carregarRetomadaCheckout() {
    try {
        const valorSalvo = sessionStorage.getItem(CHAVE_RETOMADA_CHECKOUT);
        if (!valorSalvo) return null;
        const dados = JSON.parse(valorSalvo);
        if (
            !dados
            || !fretesValidos.includes(dados.frete_tipo)
            || !['pix', 'cartao'].includes(dados.forma_pagamento)
            || typeof dados.observacao !== 'string'
        ) {
            throw new Error('Os dados salvos para continuar o checkout são inválidos.');
        }
        return dados;
    } catch (erro) {
        console.error('Não foi possível recuperar a retomada do checkout:', erro);
        limparRetomadaCheckout();
        return null;
    }
}

function limparRetomadaCheckout() {
    try {
        sessionStorage.removeItem(CHAVE_RETOMADA_CHECKOUT);
    } catch (erro) {
        console.error('Não foi possível limpar a retomada do checkout:', erro);
    }
}

function escaparTextoHTML(valor) {
    return String(valor ?? '').replace(/[&<>"']/g, caractere => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    })[caractere]);
}

function ampliarImagemProduto(botao) {
    const dialogo = document.getElementById('imageZoomDialog');
    const imagem = botao.querySelector('.product-main-image');
    const preview = document.getElementById('imageZoomPreview');
    if (!dialogo || !imagem || !preview) return;
    preview.src = imagem.currentSrc || imagem.src;
    preview.alt = imagem.alt;
    dialogo.showModal();
}

function salvarObservacaoPedido() {
    const status = document.getElementById('observacaoPedidoStatus');
    observacaoPedido = document.getElementById('observacaoPedido')?.value || '';
    if (!usuarioLogado) {
        if (status) status.textContent = 'Entre na sua conta para salvar a observação.';
        return;
    }
    if (status) status.textContent = 'Salvando...';
    fetch('/api/carrinho/observacao', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ observacao: observacaoPedido }),
    }).then(resposta => resposta.json()).then(dados => {
        if (status) status.textContent = dados.sucesso ? 'Observação salva.' : (dados.mensagem || 'Não foi possível salvar.');
    }).catch(() => {
        if (status) status.textContent = 'Não foi possível salvar agora. A observação será enviada ao finalizar.';
    });
}

function carregarCarrinhoLocal() {
    try {
        const carrinhoSalvo = localStorage.getItem(CHAVE_CARRINHO_LOCAL);
        if (carrinhoSalvo === null) return false;

        const itensSalvos = JSON.parse(carrinhoSalvo);
        if (!Array.isArray(itensSalvos)) {
            throw new Error('O carrinho salvo não contém uma lista válida.');
        }

        carrinho = itensSalvos.map((item, indice) => ({
            ...item,
            cartId: item.cartId || `${item.id}_${item.cor || 'sem-cor'}_${item.tamanho || indice}`,
        }));
        return true;
    } catch (erro) {
        console.error('Não foi possível recuperar o carrinho do armazenamento local:', erro);
        return false;
    }
}

function salvarCarrinhoLocal() {
    try {
        localStorage.setItem(CHAVE_CARRINHO_LOCAL, JSON.stringify(carrinho));
        carrinhoLocalDisponivel = true;
    } catch (erro) {
        console.error('Não foi possível salvar o carrinho no armazenamento local:', erro);
    }
}

function limparCarrinhoLocal() {
    try {
        localStorage.removeItem(CHAVE_CARRINHO_LOCAL);
        carrinhoLocalDisponivel = false;
    } catch (erro) {
        console.error('Não foi possível limpar o carrinho do armazenamento local:', erro);
    }
}

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
        modal.dataset.limparPedidoExpirado = /expir(?:ou|ad[oa])/i.test(mensagem) ? 'true' : 'false';
        modal.style.display = 'flex';
    } else {
        alert(mensagem);
    }
}

function fecharModalCustom() {
    const modal = document.getElementById('customModal');
    if (modal) {
        const limparPedidoExpirado = modal.dataset.limparPedidoExpirado === 'true';
        modal.style.display = 'none';
        modal.dataset.limparPedidoExpirado = 'false';
        if (limparPedidoExpirado) resetarPedidoExpirado();
    }
}

function resetarPedidoExpirado() {
    pararAcompanhamentoPagamentoPix();
    checkoutProcessando = false;
    checkoutConcluido = false;
    carrinho = [];
    pedidoAtualId = null;
    carrinhoInicializado = true;
    carrinhoReservadoNoInicio = false;
    reservaInicialCarrinho = [];
    freteSelecionadoValor = 0;
    freteSelecionadoTipo = 'Não selecionado';
    observacaoPedido = '';

    const campoObservacao = document.getElementById('observacaoPedido');
    if (campoObservacao) campoObservacao.value = '';
    document.querySelectorAll('input[name="opcaoFrete"]').forEach(opcao => { opcao.checked = false; });
    atualizarResumoFrete();
    atualizarCarrinho(false);
    limparCarrinhoLocal();
}

// ==========================================
// FUNÇÕES DE AUTENTICAÇÃO E LOGIN
// ==========================================
function abrirAuthModal() {
    const modal = document.getElementById('authModal');
    const campoNome = document.getElementById('loginNome');
    const campoWhatsapp = document.getElementById('loginWhatsapp');
    if (campoNome && !campoNome.value) campoNome.value = nomeClienteAtual;
    if (campoWhatsapp && !campoWhatsapp.value) campoWhatsapp.value = formatarTelefoneCliente(whatsappClienteAtual);
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
    .then(async resposta => {
        const data = await resposta.json();
        if (!resposta.ok || !data.sucesso) throw new Error(data.mensagem || 'Não foi possível continuar.');
        window.location.reload();
    })
    .catch(erro => mostrarAviso(erro.message || 'Falha de conexão. Tente novamente.', 'Não foi possível continuar'));
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
    toggleCarrinho();
}

function toggleCarrinho() {
    const drawer = document.getElementById('cartDrawer');
    const overlay = document.getElementById('cartOverlay');
    if (drawer && overlay) {
        drawer.classList.toggle('open');
        overlay.classList.toggle('open');
    }
}

function fecharCarrinho() {
    document.getElementById('cartDrawer')?.classList.remove('open');
    document.getElementById('cartOverlay')?.classList.remove('open');
}

function abrirModalGrade(id, nome, variantes, imagem, referencia = '') {
    if (!carrinhoInicializado) {
        mostrarAviso('Aguarde a recuperação da sua sacola antes de escolher produtos.', 'Carregando pedido');
        return;
    }
    
    const variantesDisponiveis = (variantes || []).map(variante => ({
        ...variante,
        tamanhos: (variante.tamanhos || []).map(tamanho => ({ ...tamanho })),
    }));
    if (carrinhoReservadoNoInicio) {
        reservaInicialCarrinho.filter(item => Number(item.id) === Number(id)).forEach(item => {
            const variante = variantesDisponiveis.find(opcao => String(opcao.cor || '').trim().toLocaleLowerCase() === String(item.cor || '').trim().toLocaleLowerCase());
            const tamanho = (variante?.tamanhos || []).find(opcao => String(opcao.nome).toLocaleLowerCase() === String(item.tamanho).toLocaleLowerCase());
            if (tamanho) tamanho.estoque = Number(tamanho.estoque || 0) + Number(item.quantidade || 0);
        });
    }
    produtoTemp = { id, nome, imagem, referencia, variantes: variantesDisponiveis, varianteSelecionada: 0, selecao: {} };
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
    document.getElementById('gradeAddButton').disabled = !comprasAtivas || pecas === 0;
}

function fecharModalGrade() {
    document.getElementById('gradeModal').style.display = 'none';
}

function criarItensSelecionadosDaGrade(itensSelecionados) {
    return itensSelecionados.map(({ variante, tamanho, quantidade }) => ({
        cartId: `${produtoTemp.id}_${variante.cor}_${tamanho.nome}`,
        id: produtoTemp.id,
        referencia: produtoTemp.referencia,
        tamanho: tamanho.nome,
        cor: variante.cor,
        nome: produtoTemp.nome,
        preco: Number(tamanho.preco),
        quantidade,
        imagem: produtoTemp.imagem,
        estoqueMax: Number(tamanho.estoque),
    }));
}

function mesclarItensDaGrade(carrinhoAtual, novosItens) {
    const carrinhoMesclado = carrinhoAtual.map(item => ({ ...item }));
    novosItens.forEach(novoItem => {
        const existente = carrinhoMesclado.find(item => item.cartId === novoItem.cartId);
        if (existente) {
            existente.quantidade += novoItem.quantidade;
        } else {
            carrinhoMesclado.push({ ...novoItem });
        }
    });
    return carrinhoMesclado;
}

function adicionarItensDaGrade(novosItens) {
    carrinho = mesclarItensDaGrade(carrinho, novosItens);
    fecharModalGrade();
    atualizarCarrinho();
    if (!document.getElementById('cartDrawer').classList.contains('open')) toggleCarrinho();
}

function confirmarGrade() {
    if (!comprasAtivas) {
        mostrarAviso('As compras estão temporariamente pausadas. Tente novamente mais tarde.', 'Compras pausadas');
        return;
    }
    if (!carrinhoInicializado) {
        mostrarAviso('Aguarde a recuperação da sua sacola antes de adicionar produtos.', 'Carregando pedido');
        return;
    }
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

    const novosItens = criarItensSelecionadosDaGrade(itensSelecionados);
    if (!clienteIdentificado()) {
        itensPendentesIdentificacao = novosItens;
        document.getElementById('identificacaoNome').value = nomeClienteAtual;
        document.getElementById('identificacaoWhatsapp').value = formatarTelefoneCliente(whatsappClienteAtual);
        document.getElementById('identificacaoModal').style.display = 'flex';
        document.getElementById('identificacaoNome').focus();
        return;
    }

    adicionarItensDaGrade(novosItens);
}

function fecharModalIdentificacao() {
    const modal = document.getElementById('identificacaoModal');
    if (modal) modal.style.display = 'none';
    itensPendentesIdentificacao = null;
}

async function confirmarIdentificacaoCliente(evento) {
    evento.preventDefault();
    const campoNome = document.getElementById('identificacaoNome');
    const campoWhatsapp = document.getElementById('identificacaoWhatsapp');
    const erroNome = document.getElementById('identificacaoNomeErro');
    const erroWhatsapp = document.getElementById('identificacaoWhatsappErro');
    const erroEnvio = document.getElementById('identificacaoEnvioErro');
    const botao = document.getElementById('identificacaoConfirmar');
    const nome = campoNome.value.trim().replace(/\s+/g, ' ');
    const telefoneFormatado = campoWhatsapp.value.trim();
    const digitos = telefoneFormatado.replace(/\D/g, '');

    erroNome.textContent = nome.length < 2 ? 'Informe seu nome (mínimo de 2 caracteres).' : '';
    erroWhatsapp.textContent = telefoneClienteValido(digitos)
        ? ''
        : 'Informe um WhatsApp válido no formato (DDD) 9 0000-0000.';
    erroEnvio.textContent = '';
    if (erroNome.textContent || erroWhatsapp.textContent || !itensPendentesIdentificacao) return;

    botao.disabled = true;
    botao.textContent = 'SALVANDO...';
    try {
        if (usuarioLogado) {
            const respostaIdentificacao = await fetch('/api/cliente/identificar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nome, whatsapp: telefoneFormatado }),
            });
            const dadosIdentificacao = await respostaIdentificacao.json();
            if (!respostaIdentificacao.ok || !dadosIdentificacao.sucesso) {
                throw new Error(dadosIdentificacao.mensagem || 'Não foi possível salvar sua identificação.');
            }
        }

        const carrinhoNovo = mesclarItensDaGrade(carrinho, itensPendentesIdentificacao);
        const sincronizacao = sincronizacaoCarrinhoPendente.catch(() => {}).then(async () => {
            const endpoint = usuarioLogado ? '/api/carrinho/sync' : '/api/carrinho/visitante';
            const corpo = {
                carrinho: carrinhoNovo,
                frete_tipo: freteSelecionadoTipo,
            };
            if (usuarioLogado) {
                corpo.pedido_id = pedidoAtualId;
                corpo.frete = freteSelecionadoValor;
                corpo.observacao = observacaoPedido;
            } else {
                corpo.nome = nome;
                corpo.whatsapp = telefoneFormatado;
            }
            const resposta = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(corpo),
            });
            const dados = await resposta.json();
            if (!resposta.ok || !dados.sucesso) {
                throw new Error(dados.mensagem || 'Não foi possível salvar sua sacola.');
            }
            return dados;
        });
        sincronizacaoCarrinhoPendente = sincronizacao;
        const dados = await sincronizacao;
        if (Array.isArray(dados.carrinho)) {
            carrinho = dados.carrinho.map((item, indice) => ({
                ...item,
                cartId: item.cartId || `${item.id}_${item.cor || 'sem-cor'}_${item.tamanho || indice}`,
            }));
        } else {
            carrinho = carrinhoNovo;
        }
        if (dados.pedido_id) pedidoAtualId = dados.pedido_id;
        nomeClienteAtual = nome;
        whatsappClienteAtual = digitos;
        itensPendentesIdentificacao = null;
        fecharModalIdentificacao();
        fecharModalGrade();
        atualizarCarrinho(false);
        if (!document.getElementById('cartDrawer').classList.contains('open')) toggleCarrinho();
    } catch (erro) {
        erroEnvio.textContent = erro.message || 'Não foi possível salvar sua identificação. Tente novamente.';
    } finally {
        botao.disabled = false;
        botao.textContent = 'CONFIRMAR E ADICIONAR';
    }
}

function alterarQuantidade(cartId, delta) {
    if (!carrinhoInicializado) {
        mostrarAviso('Aguarde a recuperação da sua sacola antes de alterar as quantidades.', 'Carregando pedido');
        return;
    }
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

function removerItemCarrinho(cartId) {
    if (!carrinhoInicializado) {
        mostrarAviso('Aguarde a recuperação da sua sacola antes de remover itens.', 'Carregando pedido');
        return;
    }
    carrinho = carrinho.filter(item => item.cartId !== cartId);
    atualizarCarrinho();
}

function atualizarProgressoMinimoAtacado(subtotal) {
    if (pedidoSemMinimo) return;
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

function atualizarEstadoBotaoCheckout() {
    const botaoCheckout = document.getElementById('checkoutButton');
    const avisoCheckout = document.getElementById('checkoutBlocker');
    if (!botaoCheckout) return;

    if (checkoutConcluido) {
        botaoCheckout.disabled = true;
        if (avisoCheckout) {
            avisoCheckout.hidden = true;
            avisoCheckout.textContent = '';
        }
        return;
    }

    if (checkoutProcessando) {
        botaoCheckout.disabled = true;
        if (avisoCheckout) {
            avisoCheckout.hidden = false;
            avisoCheckout.textContent = 'Aguarde enquanto preparamos seu pedido.';
        }
        return;
    }

    const subtotalCentavos = carrinho.reduce(
        (total, item) => total + Math.round(Number(item.preco) * 100) * Number(item.quantidade),
        0,
    );
    const metodoPagamento = document.querySelector('input[name="metodoPagamento"]:checked')?.value;
    const radioFrete = document.querySelector('input[name="opcaoFrete"]:checked');
    const tipoFrete = radioFrete?.getAttribute('data-tipo') || freteSelecionadoTipo;
    const itemEstoqueInsuficiente = carrinho.find(item =>
        item.estoqueMax !== null
        && item.estoqueMax !== undefined
        && Number.isFinite(Number(item.estoqueMax))
        && Number(item.quantidade) > Number(item.estoqueMax)
    );
    let pendencia = '';

    if (!comprasAtivas) pendencia = 'As compras estão temporariamente pausadas.';
    else if (!carrinhoInicializado) pendencia = 'Aguarde a recuperação da sua sacola.';
    else if (carrinho.length === 0) pendencia = 'Adicione produtos à sacola para continuar.';
    else if (!pedidoSemMinimo && subtotalCentavos < 33000) {
        const falta = ((33000 - subtotalCentavos) / 100).toFixed(2).replace('.', ',');
        pendencia = `Adicione mais R$ ${falta} em produtos para atingir o mínimo de atacado.`;
    } else if (itemEstoqueInsuficiente) {
        pendencia = `Estoque insuficiente para ${itemEstoqueInsuficiente.nome}, tamanho ${itemEstoqueInsuficiente.tamanho}. Ajuste a quantidade para continuar.`;
    } else if (!['pix', 'cartao'].includes(metodoPagamento)) {
        pendencia = 'Selecione PIX ou Cartão de Crédito.';
    } else if (!fretesValidos.includes(tipoFrete)) {
        pendencia = 'Escolha uma forma de envio para liberar a finalização.';
    }

    botaoCheckout.disabled = Boolean(pendencia);
    if (avisoCheckout) {
        avisoCheckout.textContent = pendencia;
        avisoCheckout.hidden = !pendencia;
    }
}

function atualizarCarrinho(sincronizarServidor = true) {
    const cartItemsContainer = document.getElementById('cartItems');
    const cartCount = document.getElementById('cartCount');
    const cartCountMobile = document.getElementById('cartCountMobile');
    const cartSubtotal = document.getElementById('cartSubtotal');
    const cartDrawerTotal = document.getElementById('cartDrawerTotal');

    if (!cartItemsContainer) return;

    salvarCarrinhoLocal();

    const totalItensCount = carrinho.reduce((acc, item) => acc + item.quantidade, 0);
    if (cartCount) cartCount.innerText = totalItensCount;
    if (cartCountMobile) cartCountMobile.innerText = totalItensCount;

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
                    referencia: item.referencia || item.codigo || '-',
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
                    <div style="display: flex; gap: 10px; align-items: flex-start;">
                        ${grupo.imagem ? `<img src="${escaparTextoHTML(grupo.imagem)}" alt="${escaparTextoHTML(grupo.nome)}" style="width: 55px; height: 55px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border-color);">` : '<div role="img" aria-label="Sem foto cadastrada" style="width:55px;height:55px;display:grid;place-items:center;background:#f0edf1;color:#777;font-size:9px;text-align:center;border-radius:6px;border:1px solid var(--border-color);">Sem foto</div>'}
                        <div style="flex-grow: 1;">
                            <h4 style="font-size: 12px; margin: 0 0 4px 0; color: #111; line-height: 1.3;">${escaparTextoHTML(grupo.nome)} <span style="font-size: 10px; color: #666;">· REF ${escaparTextoHTML(grupo.referencia)}</span></h4>
                            <span style="font-size: 11px; color: #666;">${grupo.tamanhos.map(t => `${t.cor || 'Cor não definida'} · ${t.tamanho}: R$ ${t.preco.toFixed(2).replace('.', ',')}`).join(' · ')}</span>
                        </div>
                        <div style="text-align: right;">
                            <strong style="font-size: 13px; color: var(--brand-purple);">R$ ${grupo.totalValor.toFixed(2).replace('.', ',')}</strong>
                            <div style="font-size: 10px; color: #888; font-weight: 700; margin-top: 3px; text-transform: uppercase;">${grupo.totalPecas} Peça(s)</div>
                        </div>
                    </div>
                    
                    <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; background: #f8fafc; border-radius: 6px; padding: 8px; border: 1px solid #e2e8f0;">
                        ${grupo.tamanhos.map(t => `
                            <div style="display: flex; align-items: center; gap: 5px; background: #ffffff; padding: 3px 6px; border-radius: 4px; border: 1px solid #cbd5e1; box-shadow: 0 1px 2px rgba(0,0,0,0.02);">
                                <span class="cart-color-dot" style="background:${t.cor || '#1c1c1a'}" title="Cor selecionada: ${t.cor || 'Não informada'}"></span>
                                <span style="font-size: 11px; font-weight: 700; color: #334155; max-width: 70px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${t.cor || 'Cor'}</span>
                                <span style="font-size: 11px; font-weight: 800; color: var(--brand-purple); min-width: 16px; text-align: center;">${t.tamanho}</span>
                                <button onclick="alterarQuantidade('${t.cartId}', -1)" style="width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; background: #e2e8f0; color: #475569; border: none; cursor: pointer; border-radius: 3px; font-weight: bold; transition: 0.2s;" onmouseover="this.style.background='#cbd5e1'" onmouseout="this.style.background='#e2e8f0'">-</button>
                                <span style="font-size: 12px; font-weight: 700; color: #0f172a; min-width: 14px; text-align: center;">${t.quantidade}</span>
                                <button onclick="alterarQuantidade('${t.cartId}', 1)" style="width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; background: #e2e8f0; color: #475569; border: none; cursor: pointer; border-radius: 3px; font-weight: bold; transition: 0.2s;" onmouseover="this.style.background='#cbd5e1'" onmouseout="this.style.background='#e2e8f0'">+</button>
                                <button class="cart-remove-item" type="button" onclick="removerItemCarrinho('${t.cartId}')" aria-label="Remover ${t.nome}, cor ${t.cor || 'não definida'}, tamanho ${t.tamanho} da sacola">Remover</button>
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

        const totalNoFechamento = subtotal + (freteSelecionadoTipo === 'Excursão' ? 10 : 0);
        if (cartDrawerTotal) cartDrawerTotal.innerText = `R$ ${totalNoFechamento.toFixed(2).replace('.', ',')}`;
        const cartDrawerTotalLabel = document.getElementById('cartDrawerTotalLabel');
        if (cartDrawerTotalLabel) cartDrawerTotalLabel.textContent = freteSelecionadoTipo === 'Excursão' ? 'Total no fechamento:' : 'Total dos produtos:';
    }

    atualizarEstadoBotaoCheckout();

    if (usuarioLogado && sincronizarServidor && carrinhoInicializado) {
        sincronizarCarrinhoServidor().then(resultado => {
            if (!resultado.sucesso && resultado.itensRemovidos?.length) {
                mostrarAviso(resultado.mensagem, 'Sacola indisponível');
            } else if (!resultado.sucesso) {
                console.log('Não foi possível sincronizar a sacola:', resultado.mensagem);
            }
        });
    } else if (!usuarioLogado && sincronizarServidor && carrinhoInicializado) {
        sincronizarCarrinhoVisitante().then(resultado => {
            if (!resultado.sucesso) {
                if (resultado.item_indisponivel) {
                    atualizarEstadoBotaoCheckout();
                    mostrarAviso(resultado.mensagem, 'Estoque atualizado');
                } else {
                    console.log('Não foi possível sincronizar a sacola visitante:', resultado.mensagem);
                }
            }
        });
    }
}

function sincronizarCarrinhoServidor(atividadeCliente = true) {
    const sincronizacao = sincronizacaoCarrinhoPendente.catch(() => {}).then(async () => {
        const itensRemovidos = [];
        try {
            while (true) {
                const resposta = await fetch('/api/carrinho/sync', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        carrinho,
                        pedido_id: pedidoAtualId,
                        frete: freteSelecionadoValor,
                        frete_tipo: freteSelecionadoTipo,
                        observacao: observacaoPedido,
                        atividade_cliente: atividadeCliente,
                    }),
                });
                const dados = await resposta.json();
                if (resposta.ok) {
                    if (Object.prototype.hasOwnProperty.call(dados, 'pedido_id')) pedidoAtualId = dados.pedido_id;
                    if (Array.isArray(dados.carrinho)) {
                        carrinho = carrinho.map(item => {
                            const itemServidor = dados.carrinho.find(itemSalvo =>
                                mesmaVariacaoCarrinho(itemSalvo, item)
                            );
                            return itemServidor
                                ? { ...item, preco: Number(itemServidor.preco), referencia: itemServidor.referencia || item.referencia }
                                : item;
                        });
                        salvarCarrinhoLocal();
                        atualizarCarrinho(false);
                    }
                    if (itensRemovidos.length) {
                        return {
                            sucesso: false,
                            mensagem: `${itensRemovidos.join('\n')}\nOs itens indisponíveis foram removidos da sua sacola.`,
                            itensRemovidos,
                        };
                    }
                    return dados;
                }

                const itemIndisponivel = dados.item_indisponivel;
                const indiceItem = itemIndisponivel ? carrinho.findIndex(item =>
                    mesmaVariacaoCarrinho(item, itemIndisponivel)
                ) : -1;
                if (indiceItem === -1) {
                    const mensagem = dados.mensagem || 'Não foi possível sincronizar a sacola.';
                    return {
                        sucesso: false,
                        mensagem: itensRemovidos.length
                            ? `${mensagem}\n${itensRemovidos.join('\n')}\nOs itens indisponíveis foram removidos da sua sacola.`
                            : mensagem,
                        ...(itensRemovidos.length ? { itensRemovidos } : {}),
                    };
                }

                const [itemRemovido] = carrinho.splice(indiceItem, 1);
                itensRemovidos.push(dados.mensagem || `O item '${itemRemovido.nome}' (${itemRemovido.cor || 'sem cor'}, tam. ${itemRemovido.tamanho}) está indisponível.`);
                atualizarCarrinho(false);
            }
        } catch (erro) {
            const mensagem = 'Falha de conexão ao sincronizar a sacola.';
            return {
                sucesso: false,
                mensagem: itensRemovidos.length
                    ? `${mensagem}\n${itensRemovidos.join('\n')}\nOs itens indisponíveis foram removidos da sua sacola.`
                    : mensagem,
                ...(itensRemovidos.length ? { itensRemovidos } : {}),
            };
        }
    });
    sincronizacaoCarrinhoPendente = sincronizacao;
    return sincronizacao;
}

function sincronizarCarrinhoVisitante(atividadeCliente = true) {
    const sincronizacao = sincronizacaoCarrinhoPendente.catch(() => {}).then(async () => {
        try {
            const resposta = await fetch('/api/carrinho/visitante', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    carrinho,
                    frete_tipo: freteSelecionadoTipo,
                    atividade_cliente: atividadeCliente,
                }),
            });
            const dados = await resposta.json();
            if (!resposta.ok || !dados.sucesso) {
                if (dados.item_indisponivel) {
                    const item = carrinho.find(itemCarrinho =>
                        mesmaVariacaoCarrinho(itemCarrinho, dados.item_indisponivel)
                    );
                    if (item && Number.isFinite(Number(dados.estoque_disponivel))) {
                        item.estoqueMax = Number(dados.estoque_disponivel);
                        salvarCarrinhoLocal();
                        atualizarCarrinho(false);
                    }
                }
                return {
                    sucesso: false,
                    mensagem: dados.mensagem || 'Não foi possível atualizar sua sacola.',
                    item_indisponivel: dados.item_indisponivel,
                };
            }
            if (Array.isArray(dados.carrinho)) {
                carrinho = carrinho.map(item => {
                    const itemServidor = dados.carrinho.find(itemSalvo =>
                        mesmaVariacaoCarrinho(itemSalvo, item)
                    );
                    return itemServidor
                        ? {
                            ...item,
                            preco: Number(itemServidor.preco),
                            referencia: itemServidor.referencia || item.referencia,
                            estoqueMax: Number(itemServidor.estoqueMax ?? item.estoqueMax),
                        }
                        : item;
                });
                salvarCarrinhoLocal();
                atualizarCarrinho(false);
            }
            return dados;
        } catch (erro) {
            console.error('Falha ao sincronizar a sacola visitante:', erro);
            return { sucesso: false, mensagem: 'Falha de conexão ao sincronizar a sacola.' };
        }
    });
    sincronizacaoCarrinhoPendente = sincronizacao;
    return sincronizacao;
}

async function restaurarCarrinhoSalvo(retomadaCheckout = null) {
    const temSnapshotLocal = carrinhoLocalDisponivel;
    if (!usuarioLogado) {
        try {
            const resposta = await fetch('/api/carrinho/visitante');
            const dados = await resposta.json();
            if (dados.nome_cliente) nomeClienteAtual = dados.nome_cliente;
            if (dados.whatsapp) whatsappClienteAtual = String(dados.whatsapp).replace(/\D/g, '');
            if (resposta.ok && dados.sucesso && Array.isArray(dados.carrinho) && !temSnapshotLocal) {
                carrinho = dados.carrinho;
            }
        } catch (erro) {
            console.error('Não foi possível recuperar a sacola visitante:', erro);
        }
        carrinhoInicializado = true;
        atualizarCarrinho(false);
        if (carrinho.length && clienteIdentificado()) {
            const sincronizacao = await sincronizarCarrinhoVisitante(false);
            if (!sincronizacao.sucesso) mostrarAviso(sincronizacao.mensagem, 'Sacola indisponível');
        }
        return;
    }

    const cartItemsContainer = document.getElementById('cartItems');
    if (temSnapshotLocal) {
        atualizarCarrinho(false);
    } else if (cartItemsContainer) {
        cartItemsContainer.classList.remove('is-empty');
        cartItemsContainer.innerHTML = '<div class="empty-cart"><strong>Recuperando seu pedido...</strong></div>';
    }

    try {
        const resposta = await fetch('/api/carrinho');
        const dados = await resposta.json();
        if (!resposta.ok || !dados.sucesso) throw new Error(dados.mensagem || 'Não foi possível recuperar sua sacola.');

        const itensLocais = carrinho;
        const itensSalvos = Array.isArray(dados.carrinho) ? dados.carrinho : [];
        pedidoAtualId = dados.pedido_id || null;
        const itensRestaurados = temSnapshotLocal
            ? (retomadaCheckout ? mesclarCarrinhos(itensSalvos, itensLocais) : itensLocais)
            : itensSalvos;
        carrinho = itensRestaurados.map((item, indice) => ({
            ...item,
            cartId: item.cartId || `${item.id}_${item.cor || 'sem-cor'}_${item.tamanho || indice}`,
        }));
        reservaInicialCarrinho = itensSalvos.map(item => ({ ...item }));
        carrinhoReservadoNoInicio = ['ABERTO', 'PAGAMENTO'].includes(dados.status) && itensSalvos.length > 0;

        freteSelecionadoTipo = retomadaCheckout?.frete_tipo || dados.frete_tipo || 'Não selecionado';
        if (!fretesValidos.includes(freteSelecionadoTipo)) freteSelecionadoTipo = 'Não selecionado';
        freteSelecionadoValor = freteSelecionadoTipo === 'Excursão' ? 10 : 0;
        observacaoPedido = retomadaCheckout?.observacao ?? dados.observacao ?? '';
        const observacaoInput = document.getElementById('observacaoPedido');
        if (observacaoInput) observacaoInput.value = observacaoPedido;
        const linhaFrete = document.getElementById('rowFrete');
        const valorFrete = document.getElementById('cartFreteValue');
        if (linhaFrete && valorFrete && (freteSelecionadoTipo !== 'Não selecionado' || freteSelecionadoValor > 0)) {
            linhaFrete.style.display = 'flex';
            valorFrete.innerText = freteSelecionadoTipo === 'Correios' ? 'A combinar' : `R$ ${freteSelecionadoValor.toFixed(2).replace('.', ',')}`;
        }
        const labelFrete = document.getElementById('cartFreteLabel');
        if (labelFrete && freteSelecionadoTipo === 'Retirada em Surubim') labelFrete.textContent = 'Retirada em Surubim:';
        else if (labelFrete && freteSelecionadoTipo === 'Excursão') labelFrete.textContent = 'Taxa de excursão (incluída no fechamento):';
        const opcaoCorreios = document.querySelector('input[name="opcaoFrete"][data-tipo="Correios"]');
        if (opcaoCorreios) opcaoCorreios.checked = freteSelecionadoTipo === 'Correios';
        const opcaoRetirada = document.querySelector('input[name="opcaoFrete"][data-tipo="Retirada em Surubim"]');
        if (opcaoRetirada) opcaoRetirada.checked = freteSelecionadoTipo === 'Retirada em Surubim';
        const opcaoExcursao = document.querySelector('input[name="opcaoFrete"][data-tipo="Excursão"]');
        if (opcaoExcursao) opcaoExcursao.checked = freteSelecionadoTipo === 'Excursão';
        if (retomadaCheckout) {
            const opcaoPagamento = document.querySelector(`input[name="metodoPagamento"][value="${retomadaCheckout.forma_pagamento}"]`);
            if (opcaoPagamento) opcaoPagamento.checked = true;
        }
        atualizarResumoFrete();
        const cep = String(dados.endereco || '').match(/CEP:\s*(\d{8})/i)?.[1];
        if (cep && document.getElementById('cepInput')) document.getElementById('cepInput').value = cep;
        carrinhoInicializado = true;
        atualizarCarrinho(false);

        if (retomadaCheckout) {
            limparRetomadaCheckout();
            if (!document.getElementById('cartDrawer')?.classList.contains('open')) toggleCarrinho();
            await finalizarPedido();
            return;
        }

        if (dados.status === 'ABANDONADO' || temSnapshotLocal) {
            const sincronizacao = await sincronizarCarrinhoServidor(false);
            if (!sincronizacao.sucesso) mostrarAviso(sincronizacao.mensagem, 'Estoque atualizado');
        }
    } catch (erro) {
        carrinhoInicializado = true;
        atualizarCarrinho(false);
        if (retomadaCheckout) limparRetomadaCheckout();
        mostrarAviso(erro.message || 'Não foi possível recuperar sua sacola.', 'Sacola indisponível');
    }
}

function consultarCepEntrega() {
    const cepInput = document.getElementById('cepInput');
    const resultado = document.getElementById('cepResultado');
    if (!cepInput || !resultado) return;

    const cep = cepInput.value.replace(/\D/g, '');
    if (cep.length !== 8) {
        resultado.textContent = 'Digite um CEP válido com 8 dígitos.';
        return;
    }

    resultado.textContent = 'Consultando endereço...';
    fetch('/consultar-cep', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cep }),
    })
    .then(async resposta => {
        const dados = await resposta.json();
        if (!resposta.ok || !dados.sucesso) throw new Error(dados.mensagem || 'Não foi possível consultar o CEP.');
        resultado.textContent = `Endereço de entrega: ${dados.endereco_destino}`;
    })
    .catch(erro => {
        resultado.textContent = erro.message || 'Não foi possível consultar o CEP.';
    });
}

function selecionarFrete(valor, tipoTransportadora) {
    freteSelecionadoValor = tipoTransportadora === 'Excursão' ? 10 : 0;
    freteSelecionadoTipo = tipoTransportadora;

    atualizarResumoFrete();
    atualizarCarrinho();
}

function atualizarResumoFrete() {
    const rowFrete = document.getElementById('rowFrete');
    const cartFreteValue = document.getElementById('cartFreteValue');
    const excursaoBox = document.getElementById('excursaoAvisoBox');
    const labelFrete = document.getElementById('cartFreteLabel');
    const cartShippingNote = document.getElementById('cartShippingNote');
    const tipo = freteSelecionadoTipo;
    const valor = tipo === 'Excursão' ? 10 : tipo === 'Retirada em Surubim' ? 0 : freteSelecionadoValor;
    const selecionado = fretesValidos.includes(tipo);

    if (rowFrete && cartFreteValue) {
        rowFrete.style.display = selecionado ? 'flex' : 'none';
        if (labelFrete) labelFrete.textContent = tipo === 'Retirada em Surubim' ? 'Retirada em Surubim:' : tipo === 'Excursão' ? 'Taxa de excursão (incluída no fechamento):' : 'Frete Correios (a combinar):';
        cartFreteValue.innerText = tipo === 'Correios' ? 'A combinar' : `R$ ${valor.toFixed(2).replace('.', ',')}`;
    }
    if (excursaoBox) {
        if (tipo === 'Excursão') {
            excursaoBox.style.display = 'block';
            excursaoBox.innerHTML = '<strong>Taxa fixa de R$ 10,00 incluída no valor do boleto.</strong> Os detalhes da excursão serão combinados depois.';
        } else if (tipo === 'Retirada em Surubim') {
            excursaoBox.style.display = 'block';
            excursaoBox.innerHTML = '<strong>Retirada em Surubim sem custo de envio.</strong>';
        } else {
            excursaoBox.style.display = 'none';
        }
    }
    if (cartShippingNote) {
        cartShippingNote.textContent = tipo === 'Excursão'
            ? 'O valor do fechamento inclui os produtos e a taxa de excursão de R$ 10,00.'
            : tipo === 'Retirada em Surubim'
                ? 'Sem custo de envio.'
                : 'O boleto inclui somente os produtos. O frete dos Correios será combinado e pago à parte.';
    }
}

function esvaziarCarrinhoPedido() {
    pararAcompanhamentoPagamentoPix();
    carrinho = [];
    freteSelecionadoValor = 0;
    freteSelecionadoTipo = 'Não selecionado';
    observacaoPedido = '';

    const campoObservacao = document.getElementById('observacaoPedido');
    if (campoObservacao) campoObservacao.value = '';
    document.querySelectorAll('input[name="opcaoFrete"]').forEach(opcao => { opcao.checked = false; });
    atualizarResumoFrete();
    atualizarCarrinho(false);
    limparCarrinhoLocal();
}

function pararAcompanhamentoPagamentoPix() {
    window.clearTimeout(temporizadorStatusPix);
    temporizadorStatusPix = null;
    acompanhamentoPixAtivo = false;
}

function mostrarConfirmacaoPagamentoPix(resumo, urlWhatsapp) {
    const painelPagamento = document.getElementById('pixPaymentPanel');
    const painelConfirmacao = document.getElementById('pixConfirmationPanel');
    if (!painelConfirmacao || !resumo) return;

    const formatarValor = valor => new Intl.NumberFormat('pt-BR', {
        style: 'currency',
        currency: 'BRL',
    }).format(Number(valor || 0));
    const definirTexto = (id, texto) => {
        const elemento = document.getElementById(id);
        if (elemento) elemento.textContent = texto;
    };

    if (painelPagamento) {
        painelPagamento.hidden = true;
        painelPagamento.classList.add('hidden');
    }
    definirTexto('pixPaymentStatus', 'Pagamento confirmado!');
    definirTexto('pixConfirmationOrder', `Pedido #${resumo.numero_pedido}${resumo.nome_cliente ? ` · ${resumo.nome_cliente}` : ''}`);

    const listaItens = document.getElementById('pixConfirmationItems');
    if (listaItens) {
        listaItens.replaceChildren();
        resumo.itens.forEach(item => {
            const linha = document.createElement('li');
            const descricao = document.createElement('span');
            descricao.textContent = `${item.quantidade}x ${item.descricao} · Ref. ${item.referencia} · ${item.cor} · Tam. ${item.tamanho} · ${formatarValor(item.valor_unitario)} cada`;
            const subtotal = document.createElement('strong');
            subtotal.textContent = formatarValor(item.subtotal);
            linha.append(descricao, subtotal);
            listaItens.appendChild(linha);
        });
    }

    definirTexto('pixConfirmationSubtotal', formatarValor(resumo.subtotal));
    const freteLinha = document.getElementById('pixConfirmationFreightRow');
    const tipoFrete = String(resumo.tipo_frete || '');
    definirTexto('pixConfirmationFreightLabel', tipoFrete === 'Correios'
        ? 'Frete dos Correios (pago à parte)'
        : tipoFrete === 'Excursão'
            ? 'Frete por excursão (incluído)'
            : 'Retirada em Surubim');
    definirTexto('pixConfirmationFreight', tipoFrete === 'Retirada em Surubim'
        ? 'Sem custo'
        : tipoFrete === 'Correios'
            ? 'A combinar'
            : formatarValor(resumo.frete));
    if (freteLinha) freteLinha.hidden = false;

    const descontoLinha = document.getElementById('pixConfirmationDiscountRow');
    if (descontoLinha) descontoLinha.hidden = !(Number(resumo.desconto) > 0);
    definirTexto('pixConfirmationDiscount', formatarValor(resumo.desconto));
    definirTexto('pixConfirmationPayment', resumo.forma_pagamento || 'Pix');
    definirTexto('pixConfirmationTotal', formatarValor(resumo.total));

    const botaoWhatsapp = document.getElementById('pixConfirmationWhatsapp');
    if (botaoWhatsapp && resumo.numero_whatsapp && resumo.mensagem_whatsapp) {
        botaoWhatsapp.href = `https://wa.me/${encodeURIComponent(resumo.numero_whatsapp)}?text=${encodeURIComponent(resumo.mensagem_whatsapp)}`;
        botaoWhatsapp.hidden = false;
    } else if (botaoWhatsapp && urlWhatsapp) {
        botaoWhatsapp.href = urlWhatsapp;
        botaoWhatsapp.hidden = false;
    } else if (botaoWhatsapp) {
        botaoWhatsapp.hidden = true;
    }
    painelConfirmacao.hidden = false;
    painelConfirmacao.classList.remove('hidden');
}

function acompanharPagamentoPix(pedidoId) {
    pararAcompanhamentoPagamentoPix();
    pedidoPixMonitoradoId = pedidoId;
    acompanhamentoPixAtivo = true;
    const consultarStatus = async () => {
        if (!acompanhamentoPixAtivo) return;
        const secaoPix = document.getElementById('pix-section');
        const painelPagamento = document.getElementById('pixPaymentPanel');
        if (secaoPix?.hidden || painelPagamento?.hidden) {
            pararAcompanhamentoPagamentoPix();
            return;
        }
        try {
            const resposta = await fetch(`/api/pedidos/${encodeURIComponent(pedidoId)}/resumo`, {
                cache: 'no-store',
                headers: { Accept: 'application/json' },
            });
            if (!resposta.ok) throw new Error(`Falha ao consultar o pedido (HTTP ${resposta.status}).`);
            const dados = await resposta.json();
            if (!dados.sucesso) throw new Error(dados.mensagem || 'Não foi possível consultar o pedido.');

            const statusPagamento = document.getElementById('pixPaymentStatus');
            if (dados.pagamento_confirmado) {
                mostrarConfirmacaoPagamentoPix(dados.resumo, dados.url_whatsapp);
                pararAcompanhamentoPagamentoPix();
                return;
            }
            if (dados.status === 'EXPIRADO') {
                const painelPix = document.getElementById('pixPaymentPanel');
                const pixExpirado = document.getElementById('pixExpiredStatus');
                if (painelPix) painelPix.hidden = true;
                if (pixExpirado) {
                    pixExpirado.textContent = 'Este PIX expirou. Volte à loja para iniciar um novo pedido.';
                    pixExpirado.hidden = false;
                }
                pararAcompanhamentoPagamentoPix();
                return;
            }
            if (!['PAGAMENTO', 'ABERTO'].includes(dados.status)) {
                if (statusPagamento) statusPagamento.textContent = `Status atual do pedido: ${dados.status}.`;
                pararAcompanhamentoPagamentoPix();
                return;
            }
        } catch (error) {
            console.error('Não foi possível atualizar o status do pagamento PIX:', error);
        }
        if (acompanhamentoPixAtivo) {
            temporizadorStatusPix = window.setTimeout(consultarStatus, 3000);
        }
    };
    temporizadorStatusPix = window.setTimeout(consultarStatus, 3000);
}

window.addEventListener('pagehide', pararAcompanhamentoPagamentoPix);
window.addEventListener('pageshow', () => {
    const painelPagamento = document.getElementById('pixPaymentPanel');
    if (painelPagamento && !painelPagamento.hidden && pedidoPixMonitoradoId && !acompanhamentoPixAtivo) {
        acompanharPagamentoPix(pedidoPixMonitoradoId);
    }
});

async function finalizarPedido(event) {
    event?.preventDefault();
    const metodoPagamento = document.querySelector('input[name="metodoPagamento"]:checked')?.value || 'pix';

    if (!comprasAtivas) {
        mostrarAviso('As compras estão temporariamente pausadas. Tente novamente mais tarde.', 'Compras pausadas');
        return;
    }
    if (!carrinhoInicializado) {
        mostrarAviso('Aguarde a recuperação da sua sacola antes de finalizar o pedido.', 'Carregando pedido');
        return;
    }
    if (!fretesValidos.includes(freteSelecionadoTipo)) {
        mostrarAviso('Escolha uma forma de envio antes de finalizar o pedido.', 'Frete obrigatório');
        return;
    }
    if (!['pix', 'cartao'].includes(metodoPagamento)) {
        mostrarAviso('Selecione PIX ou Cartão de Crédito antes de finalizar o pedido.', 'Forma de pagamento obrigatória');
        return;
    }
    if (carrinho.length === 0) {
        mostrarAviso('Seu carrinho está vazio.', 'Carrinho Vazio');
        return;
    }

    if (!usuarioLogado) {
        if (salvarRetomadaCheckout()) abrirAuthModal();
        return;
    }

    const subtotalAtual = carrinho.reduce((acc, item) => acc + Math.round(Number(item.preco) * 100) * Number(item.quantidade), 0) / 100;
    if (!pedidoSemMinimo && subtotalAtual < 330.00) {
        const falta = 330.00 - subtotalAtual;
        mostrarAviso(`Adicione mais <strong>R$ ${falta.toFixed(2).replace('.', ',')}</strong> em produtos para finalizar o pedido.`, "Pedido incompleto");
        return;
    }

    const btnCheckout = document.getElementById('checkoutButton');
    checkoutProcessando = true;
    if (btnCheckout) {
        btnCheckout.innerText = 'Preparando pedido...';
    }
    atualizarEstadoBotaoCheckout();

    try {
        const sincronizacao = await sincronizarCarrinhoServidor();
        if (!sincronizacao.sucesso) {
            mostrarAviso(sincronizacao.mensagem || 'Não foi possível atualizar sua sacola.', 'Sacola indisponível');
            checkoutProcessando = false;
            if (btnCheckout) {
                btnCheckout.innerText = 'Finalizar Pedido';
            }
            atualizarEstadoBotaoCheckout();
            return;
        }

        const response = await fetch('/checkout-mercadopago', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                forma_pagamento: metodoPagamento,
                frete_tipo: freteSelecionadoTipo,
                observacao: observacaoPedido,
            }),
        });
        const data = await response.json();

        if (
            response.ok &&
            data.success === true &&
            data.forma_pagamento === 'especial' &&
            data.pedido_id
        ) {
            esvaziarCarrinhoPedido();
            window.location.href = `/pedido/${encodeURIComponent(data.pedido_id)}/retorno`;
            return;
        }

        if (metodoPagamento === 'cartao') {
            if (
                !response.ok ||
                data.success !== true ||
                !data.pedido_id ||
                data.forma_pagamento !== 'cartao' ||
                !data.url_whatsapp
            ) {
                mostrarAviso(data.message || data.mensagem || data.error || 'Não foi possível registrar o pedido para pagamento com cartão.', 'Não foi possível finalizar');
                checkoutProcessando = false;
                if (btnCheckout) {
                    btnCheckout.innerText = 'Finalizar Pedido';
                }
                atualizarEstadoBotaoCheckout();
                return;
            }

            esvaziarCarrinhoPedido();
            window.location.href = data.url_whatsapp;
            return;
        }

        if (!response.ok || data.error || data.sucesso === false) {
            mostrarAviso(data.mensagem || data.error || 'Erro ao gerar PIX, tente novamente.', 'Não foi possível gerar o PIX');
            checkoutProcessando = false;
            if (btnCheckout) {
                btnCheckout.innerText = 'Finalizar Pedido';
            }
            atualizarEstadoBotaoCheckout();
            return;
        }

        if (
            response.ok &&
            (data.success === true || data.sucesso === true) &&
            ['pix', 'PIX'].includes(data.forma_pagamento) &&
            data.pedido_id &&
            data.qr_code &&
            data.qr_code_base64
        ) {
            const secaoPix = document.getElementById('pix-section');
            const painelPix = document.getElementById('pixPaymentPanel');
            const imagemPix = document.getElementById('pixQrCodeImage');
            const codigoPix = document.getElementById('pixCopyPasteCode');
            if (!secaoPix || !painelPix || !imagemPix || !codigoPix) {
                throw new Error('Não foi possível exibir os dados do pagamento PIX.');
            }
            checkoutProcessando = false;
            checkoutConcluido = true;
            secaoPix.hidden = false;
            secaoPix.classList.remove('hidden');
            const pixExpirado = document.getElementById('pixExpiredStatus');
            if (pixExpirado) {
                pixExpirado.hidden = true;
                pixExpirado.textContent = '';
            }
            imagemPix.src = `data:image/png;base64,${data.qr_code_base64}`;
            codigoPix.value = data.qr_code;
            painelPix.classList.remove('hidden');
            atualizarMetodoPagamentoSelecionado();
            limparCarrinhoLocal();
            const statusPagamentoPix = document.getElementById('pixPaymentStatus');
            if (statusPagamentoPix) statusPagamentoPix.textContent = 'Aguardando confirmação do pagamento pelo Mercado Pago.';
            acompanharPagamentoPix(data.pedido_id);
            document.getElementById('pixCopyStatus').textContent = '';
            if (btnCheckout) {
                btnCheckout.innerText = 'PIX gerado';
            }
            atualizarEstadoBotaoCheckout();
            if (!document.getElementById('radioCartao')?.checked) {
                painelPix.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        } else if (data.sucesso && data.url_whatsapp) {
            esvaziarCarrinhoPedido();
            if (data.status === 'PAGO' && data.mostrar_paga_fora_do_site) {
                mostrarAviso('Pedido registrado como pago fora do site e enviado para o WhatsApp da loja.', 'Pedido pago fora do site');
            }
            window.location.href = data.url_whatsapp;
        } else {
            mostrarAviso(data.mensagem || 'Não foi possível concluir o pedido.', 'Atenção');
            checkoutProcessando = false;
            if (btnCheckout) {
                btnCheckout.innerText = 'Finalizar Pedido';
            }
            atualizarEstadoBotaoCheckout();
        }
    } catch (error) {
        console.error('Não foi possível concluir o pedido:', error);
        mostrarAviso('Erro de conexão ao processar o pedido.', 'Erro de Conexão');
        checkoutProcessando = false;
        if (btnCheckout) {
            btnCheckout.innerText = 'Finalizar Pedido';
        }
        atualizarEstadoBotaoCheckout();
    }
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
                    abrirModalGrade(produto.id, produto.nome, produto.variantes, produto.imagem_url, produto.codigo);
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
    let indiceSolicitado = 0;
    let sequenciaAlteracao = 0;
    let pausado = false;
    const carregamentos = slides.map((slide, indice) => (
        indice === 0 ? Promise.resolve(true) : null
    ));
    const carregarSlide = indice => {
        if (!carregamentos[indice]) {
            carregamentos[indice] = new Promise(resolve => {
                const imagem = new Image();
                const aplicarImagem = () => {
                    slides[indice].style.backgroundImage = `url("${slides[indice].dataset.heroImage}")`;
                    slides[indice].dataset.heroLoaded = 'true';
                    resolve(true);
                };
                imagem.onload = aplicarImagem;
                imagem.onerror = aplicarImagem;
                imagem.src = slides[indice].dataset.heroImage;
            });
        }
        return carregamentos[indice];
    };
    const mostrarSlide = indice => {
        indiceSolicitado = (indice + slides.length) % slides.length;
        const sequencia = ++sequenciaAlteracao;
        carregarSlide(indiceSolicitado).then(carregado => {
            if (!carregado || sequencia !== sequenciaAlteracao) return;
            indiceAtual = indiceSolicitado;
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

const observacaoPedidoInput = document.getElementById('observacaoPedido');
if (observacaoPedidoInput) {
    observacaoPedidoInput.addEventListener('input', () => {
        observacaoPedido = observacaoPedidoInput.value;
        window.clearTimeout(temporizadorObservacaoPedido);
        temporizadorObservacaoPedido = window.setTimeout(salvarObservacaoPedido, 500);
    });
}

const avisoPagamentoCartao = document.getElementById('avisoPagamentoCartao');
const secaoPix = document.getElementById('pix-section');
const radioPix = document.getElementById('radioPix');
const radioCartao = document.getElementById('radioCartao');
function atualizarMetodoPagamentoSelecionado() {
    const cartaoSelecionado = radioCartao?.checked === true;
    if (avisoPagamentoCartao) {
        avisoPagamentoCartao.classList.toggle('hidden', !cartaoSelecionado);
        avisoPagamentoCartao.hidden = !cartaoSelecionado;
    }
    if (secaoPix) {
        secaoPix.classList.toggle('hidden', cartaoSelecionado);
        secaoPix.hidden = cartaoSelecionado;
    }
    const painelPagamento = document.getElementById('pixPaymentPanel');
    if (cartaoSelecionado) {
        pararAcompanhamentoPagamentoPix();
    } else if (painelPagamento && !painelPagamento.hidden && pedidoPixMonitoradoId) {
        acompanharPagamentoPix(pedidoPixMonitoradoId);
    }
    atualizarEstadoBotaoCheckout();
}

radioPix?.addEventListener('change', atualizarMetodoPagamentoSelecionado);
radioCartao?.addEventListener('change', atualizarMetodoPagamentoSelecionado);
atualizarMetodoPagamentoSelecionado();

const botaoCheckout = document.getElementById('checkoutButton');
if (botaoCheckout) {
    botaoCheckout.addEventListener('click', finalizarPedido);
}

const botaoCopiarPix = document.getElementById('copyPixCodeButton');
if (botaoCopiarPix) {
    botaoCopiarPix.addEventListener('click', async () => {
        const codigoPix = document.getElementById('pixCopyPasteCode');
        const statusCopiarPix = document.getElementById('pixCopyStatus');
        if (!codigoPix || !codigoPix.value) return;
        try {
            await navigator.clipboard.writeText(codigoPix.value);
            if (statusCopiarPix) statusCopiarPix.textContent = 'Código PIX copiado.';
        } catch (erro) {
            codigoPix.focus();
            codigoPix.select();
            if (statusCopiarPix) statusCopiarPix.textContent = 'Não foi possível copiar automaticamente. Selecione e copie o código.';
        }
    });
}

const botaoEntendiAviso = document.getElementById('btnEntendiAviso');
if (botaoEntendiAviso) {
    botaoEntendiAviso.addEventListener('click', fecharModalCustom);
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('#identificacaoWhatsapp, #loginWhatsapp, #cadWhatsapp')
        .forEach(campo => campo.addEventListener('input', aplicarMascaraTelefone));
    carrinhoLocalDisponivel = carregarCarrinhoLocal();
    const retomadaCheckout = usuarioLogado ? carregarRetomadaCheckout() : null;
    const abrirCarrinho = new URLSearchParams(window.location.search).get('abrir_carrinho') === '1';
    restaurarCarrinhoSalvo(retomadaCheckout).then(() => {
        if (abrirCarrinho && carrinho.length) toggleCarrinho();
    });
});

const appIdOneSignal = document.querySelector('meta[name="onesignal-app-id"]')?.content;
if (appIdOneSignal) {
    window.OneSignalDeferred = window.OneSignalDeferred || [];
    window.OneSignalDeferred.push(async OneSignal => {
        await OneSignal.init({
            appId: appIdOneSignal,
            serviceWorkerPath: '/OneSignalSDKWorker.js',
            serviceWorkerParam: { scope: '/' },
        });
        window.leylyOneSignal = OneSignal;

        const botaoNotificacoes = document.getElementById('ativarNotificacoesCarrinho');
        const statusNotificacoes = document.getElementById('statusNotificacoesCarrinho');
        if (!botaoNotificacoes) return;
        botaoNotificacoes.disabled = false;

        const salvarAssinatura = async subscriptionId => {
            const resposta = await fetch('/api/onesignal/subscription', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ subscription_id: subscriptionId }),
            });
            const dados = await resposta.json();
            if (!resposta.ok || !dados.sucesso) {
                throw new Error(dados.mensagem || 'Não foi possível salvar a assinatura.');
            }
            if (statusNotificacoes) statusNotificacoes.textContent = 'Lembretes ativados para este dispositivo.';
        };

        OneSignal.User.PushSubscription.addEventListener('change', evento => {
            const subscriptionId = evento?.current?.id || OneSignal.User.PushSubscription.id;
            if (subscriptionId) {
                salvarAssinatura(subscriptionId).catch(erro => {
                    if (statusNotificacoes) statusNotificacoes.textContent = erro.message;
                    console.error('Falha ao salvar assinatura OneSignal.', erro);
                });
            }
        });

        botaoNotificacoes.addEventListener('click', async () => {
            botaoNotificacoes.disabled = true;
            if (statusNotificacoes) statusNotificacoes.textContent = 'Aguardando permissão do navegador...';
            try {
                await OneSignal.Notifications.requestPermission();
                const subscriptionId = OneSignal.User.PushSubscription.id;
                if (!subscriptionId) {
                    if (statusNotificacoes) statusNotificacoes.textContent = 'Permita notificações no navegador para ativar os lembretes.';
                    return;
                }
                await salvarAssinatura(subscriptionId);
            } catch (erro) {
                if (statusNotificacoes) statusNotificacoes.textContent = erro.message || 'Não foi possível ativar os lembretes.';
                console.error('Falha ao ativar notificações OneSignal.', erro);
            } finally {
                botaoNotificacoes.disabled = false;
            }
        });

        const subscriptionIdAtual = OneSignal.User.PushSubscription.id;
        if (subscriptionIdAtual) {
            salvarAssinatura(subscriptionIdAtual).catch(erro => {
                if (statusNotificacoes) statusNotificacoes.textContent = erro.message;
                console.error('Falha ao atualizar assinatura OneSignal.', erro);
            });
        }
    });
}