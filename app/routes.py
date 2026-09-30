import os
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session, current_app, flash
from app.models import Produto, ProdutoImagem, Usuario, Pedido, Admin, Visita, ImagemSite, ImportacaoEstoque
from app import db
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
import requests
import json
import re
import math
import secrets
import unicodedata
from datetime import datetime, timedelta

main_bp = Blueprint('main', __name__)
VALOR_MINIMO_ATACADO = 330.00
VALOR_FRETE_EXCURSAO = 10.00
STATUS_PEDIDO_EDITAVEIS = {'ABERTO', 'PAGAMENTO', 'PAGO', 'SEPARACAO'}
CATEGORIAS_PRODUTO = {
    'acessorios': 'Acessórios',
    'blusas-casacos': 'Blusas/Casacos',
    'calca': 'Calça',
    'conjunto-calca-top-estampado': 'Conjunto Calça e Top Estampado',
    'conjunto-calca-top-liso': 'Conjunto Calça e Top Liso',
    'short-top': 'Short e Top',
    'linha-premium': 'Linha Premium',
    'macacao': 'Macacão',
    'macaquinho': 'Macaquinho',
    'short': 'Short',
    'short-saia': 'Short/Saia',
    'top': 'Top',
    'vestido-fitness': 'Vestido Fitness',
}
EXTENSOES_IMAGEM = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
REGIOES_BRASIL = {
    'Norte': {'AC', 'AP', 'AM', 'PA', 'RO', 'RR', 'TO'},
    'Nordeste': {'AL', 'BA', 'CE', 'MA', 'PB', 'PE', 'PI', 'RN', 'SE'},
    'Centro-Oeste': {'DF', 'GO', 'MT', 'MS'},
    'Sudeste': {'ES', 'MG', 'RJ', 'SP'},
    'Sul': {'PR', 'RS', 'SC'},
}

CORES_HEX = {
    'açaí': '#59213c', 'amarelo manteiga': '#f2df9b', 'azul': '#2456a6', 'azul bebê': '#a8d6ee',
    'azul marinho': '#172b4d', 'azul neblina': '#a9c5d6', 'azul royal': '#2450bd', 'azul turquesa': '#27a9b5',
    'bege': '#d8c3a5', 'bordô': '#702637', 'branco': '#f8f8f5', 'caramelo': '#a9663d', 'cacau': '#684b3c',
    'cinza': '#858585', 'fúcsia': '#d21a79', 'grafite': '#45464b', 'laranja': '#e77832', 'lilás': '#b8a2cf',
    'marrom': '#593d32', 'marsala': '#713947', 'mostarda': '#bd941e', 'nude': '#c8a68d', 'office white': '#f4f1e9',
    'pink cereja': '#c51e62', 'preto': '#1c1c1a', 'rosa bebê': '#f0c5d1', 'rosa pink': '#df4e92',
    'rosa quente': '#df5a83', 'rosé': '#d99aa5', 'telha': '#a94e3b', 'terracota': '#b75b45', 'uva': '#54284f',
    'verde': '#5b865d', 'verde água': '#8bc9b5', 'verde jade': '#3c9b79', 'verde limão': '#93b83e',
    'verde militar': '#536247', 'verde musgo': '#626b43', 'vinho': '#692d3c', 'roxo': '#683f78',
}


def normalizar_cor(cor):
    if not isinstance(cor, str):
        return None
    cor = re.sub(r'\s+', ' ', cor.strip())
    if not cor:
        return None
    return cor[:50]


def cor_para_hex(cor):
    if not isinstance(cor, str):
        return '#8b8b8b'
    cor = cor.strip()
    if re.fullmatch(r'#[0-9a-fA-F]{6}', cor):
        return cor
    return CORES_HEX.get(cor.casefold(), '#8b8b8b')


def nome_cor(cor):
    if not isinstance(cor, str) or not cor.strip():
        return 'Cor não definida'
    cor = cor.strip()
    if re.fullmatch(r'#[0-9a-fA-F]{6}', cor):
        nome = next((nome for nome, hex_cor in CORES_HEX.items() if hex_cor.casefold() == cor.casefold()), None)
        return nome.title() if nome else f'Personalizada ({cor})'
    return cor


def categoria_por_nome(nome):
    if not isinstance(nome, str) or not nome.strip():
        return None
    texto = unicodedata.normalize('NFKD', nome.casefold())
    texto = ''.join(caractere for caractere in texto if not unicodedata.combining(caractere))
    palavras = re.sub(r'[^a-z0-9]+', ' ', texto).split()
    termos = set(palavras)
    if not termos:
        return None

    if 'premium' in termos:
        return 'linha-premium'

    calca = bool(termos.intersection({'calca', 'legging', 'leggings'}))
    top = bool(termos.intersection({'top', 'tops'}))
    short = bool(termos.intersection({'short', 'shorts'}))
    saia = 'saia' in termos

    if 'macacao' in termos:
        return 'macacao'
    if calca and top:
        return 'conjunto-calca-top-estampado' if any(palavra.startswith('estamp') for palavra in termos) else 'conjunto-calca-top-liso'
    if short and saia:
        return 'short-saia'
    if short and top:
        return 'short-top'
    if 'macaquinho' in termos:
        return 'macaquinho'
    if 'macacao' in termos:
        return 'macacao'
    if 'vestido' in termos:
        return 'vestido-fitness'
    if termos.intersection({'blusa', 'blusas', 'casaco', 'casacos', 'jaqueta', 'moletom'}):
        return 'blusas-casacos'
    if saia and short:
        return 'short-saia'
    if calca:
        return 'calca'
    if top:
        return 'top'
    if short:
        return 'short'
    if termos.intersection({'acessorio', 'acessorios', 'tiara'}):
        return 'acessorios'
    return None


def categoria_para_exibicao(produto):
    if produto.categoria in CATEGORIAS_PRODUTO:
        return produto.categoria
    categoria_inferida = categoria_por_nome(produto.nome)
    return categoria_inferida if categoria_inferida in CATEGORIAS_PRODUTO else ''


def categoria_selecionada(valor, nome_produto=''):
    categoria = str(valor or '').strip().casefold()
    if categoria:
        if categoria not in CATEGORIAS_PRODUTO:
            raise ValueError('Selecione uma categoria válida para o produto.')
        return categoria
    categoria_inferida = categoria_por_nome(nome_produto)
    return categoria_inferida if categoria_inferida in CATEGORIAS_PRODUTO else None


def link_whatsapp_cliente(numero):
    telefone = re.sub(r'\D', '', str(numero or ''))
    if len(telefone) in (10, 11):
        telefone = f'55{telefone}'
    if len(telefone) not in (12, 13) or not telefone.startswith('55'):
        return None
    return f'https://wa.me/{telefone}'


def chave_cor(cor):
    nome = nome_cor(cor)
    if nome.startswith('Personalizada ('):
        return str(cor).strip().casefold()
    return nome.casefold()


def referencia_em_uso(codigo, ignorar_id=None):
    codigo_normalizado = str(codigo or '').strip().casefold()
    if not codigo_normalizado:
        return False
    if db.engine.dialect.name == 'postgresql':
        db.session.execute(
            text('SELECT pg_advisory_xact_lock(hashtext(:codigo))'),
            {'codigo': codigo_normalizado},
        )
    consulta = Produto.query.filter(db.func.lower(db.func.trim(Produto.codigo)) == codigo_normalizado)
    if ignorar_id is not None:
        consulta = consulta.filter(Produto.id != ignorar_id)
    return consulta.first() is not None


def variantes_com_cor_hex(variantes):
    return [{**variante, 'cor_hex': cor_para_hex(variante.get('cor')), 'cor_nome': nome_cor(variante.get('cor'))} for variante in variantes]


def imagem_disponivel(caminho):
    if not isinstance(caminho, str) or not caminho.strip() or os.path.isabs(caminho):
        return False
    raiz_estatica = os.path.abspath(current_app.static_folder)
    caminho_arquivo = os.path.abspath(os.path.join(raiz_estatica, caminho))
    if os.path.commonpath((raiz_estatica, caminho_arquivo)) != raiz_estatica:
        return False
    return os.path.isfile(caminho_arquivo)


@main_bp.app_context_processor
def fornecer_variantes_imagem():
    def imagem_variacao(caminho, variante):
        base, extensao = os.path.splitext(caminho)
        if extensao.lower() == '.gif':
            return caminho
        return f'{base}.{variante}.webp'

    return {
        'imagem_variacao': imagem_variacao,
        'cor_hex': cor_para_hex,
        'nome_cor': nome_cor,
        'variantes_do_produto': variantes_do_produto,
        'variantes_com_cor_hex': variantes_com_cor_hex,
        'imagem_disponivel': imagem_disponivel,
    }

# ==========================================
# GARI DE ESTOQUE (LIMPADOR AUTOMÁTICO)
# ==========================================
def limpar_carrinhos_abandonados():
    limite = datetime.utcnow() - timedelta(minutes=30)
    expirados = Pedido.query.filter(Pedido.status.in_(['ABERTO', 'PAGAMENTO']), Pedido.data_atualizacao < limite).all()
    
    for p in expirados:
        if p.itens and p.itens != '[]':
            itens = json.loads(p.itens)
            for item in itens:
                prod = Produto.query.get(item['id'])
                if prod:
                    atualizar_estoque_variante(prod, item.get('cor'), item['tamanho'], item['quantidade'])
        
        p.status = 'ABANDONADO'
        
    if expirados:
        db.session.commit()

def salvar_imagens_produto(produto, arquivos):
    arquivos_validos = validar_arquivos_imagem(arquivos)
    if not arquivos_validos:
        return

    ordem = max((imagem.ordem for imagem in produto.imagens), default=-1) + 1
    for arquivo in arquivos_validos:
        filename = secure_filename(arquivo.filename)
        if not filename:
            continue
        nome_unico = f'{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")}_{filename}'
        save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], nome_unico)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        salvar_imagem_otimizada(arquivo, save_path, os.path.splitext(filename)[1].lower())
        caminho = f'uploads/{nome_unico}'
        if not produto.imagem_url or produto.imagem_url == 'img/default.jpg':
            produto.imagem_url = caminho
        else:
            db.session.add(ProdutoImagem(produto=produto, imagem_url=caminho, ordem=ordem))
            ordem += 1


def imagem_produto_para_url(imagem):
    if isinstance(imagem, dict):
        return imagem.get('url') or imagem.get('imagem_url')
    return imagem

def salvar_arquivo_imagem(arquivo):
    validar_arquivos_imagem([arquivo])
    filename = secure_filename(arquivo.filename)
    extensao = os.path.splitext(filename)[1].lower()
    nome_unico = f'{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")}_{filename}'
    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], nome_unico)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    salvar_imagem_otimizada(arquivo, save_path, extensao)
    return f'uploads/{nome_unico}'


def validar_arquivos_imagem(arquivos):
    arquivos_validos = [arquivo for arquivo in arquivos if arquivo and arquivo.filename]
    for arquivo in arquivos_validos:
        filename = secure_filename(arquivo.filename)
        extensao = os.path.splitext(filename)[1].lower()
        if not filename or extensao not in EXTENSOES_IMAGEM:
            raise ValueError('Envie somente imagens JPG, JPEG, PNG, WEBP ou GIF.')
        try:
            arquivo.stream.seek(0)
            with Image.open(arquivo.stream) as imagem:
                imagem.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as erro:
            raise ValueError(f'O arquivo {filename} não contém uma imagem válida.') from erro
        finally:
            arquivo.stream.seek(0)
    return arquivos_validos


def salvar_imagem_otimizada(arquivo, save_path, extensao):
    if extensao == '.gif':
        arquivo.save(save_path)
        return

    with Image.open(arquivo.stream) as imagem:
        imagem = ImageOps.exif_transpose(imagem)
        if extensao in {'.jpg', '.jpeg'}:
            imagem.convert('RGB').save(save_path, 'JPEG', quality=88, optimize=True, progressive=True)
        elif extensao == '.png':
            imagem.save(save_path, 'PNG', optimize=True)
        elif extensao == '.webp':
            imagem.save(save_path, 'WEBP', quality=88, method=6)

    gerar_variantes_imagem(save_path)

def gerar_variantes_imagem(caminho):
    with Image.open(caminho) as origem:
        imagem = ImageOps.exif_transpose(origem)
        modo = 'RGBA' if 'A' in imagem.getbands() or 'transparency' in imagem.info else 'RGB'
        imagem = imagem.convert(modo)

        galeria = imagem.copy()
        galeria.thumbnail((960, 960), Image.Resampling.LANCZOS)
        galeria.save(f'{os.path.splitext(caminho)[0]}.gallery.webp', 'WEBP', quality=82, method=6)

        miniatura = imagem.copy()
        miniatura.thumbnail((180, 220), Image.Resampling.LANCZOS)
        miniatura.save(f'{os.path.splitext(caminho)[0]}.thumb.webp', 'WEBP', quality=72, method=5)

IMAGENS_SITE_PADRAO = {
    'banner_hero': ('Banner principal', 'img/banner_hero1.jpeg'),
    'banner_hero_2': ('Banner principal - imagem 2', 'img/banner_macaquinho.jpeg'),
    'banner_hero_3': ('Banner principal - imagem 3', 'img/banner_lounge.jpeg'),
    'banner_promise': ('Banner da seção de qualidade', 'img/banner_macaquinho.jpeg'),
    'banner_macaquinho': ('Banner de macaquinhos', 'img/banner_macaquinho.jpeg'),
    'banner_lounge': ('Banner da linha casual', 'img/banner_lounge.jpeg'),
    'categoria_conjuntos': ('Categoria conjuntos', 'img/cat_conjuntos.jpeg'),
    'categoria_leggings': ('Categoria leggings', 'img/cat_leggings.jpeg'),
    'categoria_casacos': ('Categoria casacos', 'img/cat_casacos.jpeg'),
    'categoria_tops': ('Categoria tops', 'img/cat_tops.jpeg'),
}

def garantir_imagens_site():
    alterado = False
    for chave, (nome, imagem_url) in IMAGENS_SITE_PADRAO.items():
        if not ImagemSite.query.filter_by(chave=chave).first():
            db.session.add(ImagemSite(chave=chave, nome=nome, imagem_url=imagem_url))
            alterado = True
    if alterado:
        db.session.commit()

def preco_tamanho(produto, tamanho):
    return getattr(produto, f'preco_{tamanho.lower()}', None) or produto.preco

def grade_do_produto(produto):
    return produto.grade_config

def variantes_do_produto(produto):
    return [
        {
            **variante,
            'tamanhos': [
                {**tamanho, 'preco': float(tamanho.get('preco') or produto.preco)}
                for tamanho in variante.get('tamanhos', [])
            ],
        }
        for variante in produto.variantes_config
    ]


def peso_total_carrinho(carrinho, peso_por_produto):
    if not isinstance(carrinho, list) or not carrinho:
        raise ValueError('Adicione produtos ao pedido antes de calcular o frete.')
    quantidade_total = 0
    for item in carrinho:
        try:
            quantidade = int(item.get('quantidade', 0))
        except (AttributeError, TypeError, ValueError) as erro:
            raise ValueError('A quantidade de um produto é inválida.') from erro
        if quantidade <= 0:
            raise ValueError('A quantidade de um produto é inválida.')
        quantidade_total += quantidade
    return quantidade_total * peso_por_produto


def estimar_opcoes_frete(uf_origem, uf_destino, peso_gramas):
    regiao_origem = next((nome for nome, ufs in REGIOES_BRASIL.items() if uf_origem in ufs), None)
    regiao_destino = next((nome for nome, ufs in REGIOES_BRASIL.items() if uf_destino in ufs), None)
    base_pac = 15.0 if regiao_origem == regiao_destino else 28.0
    faixas_kg = max(1, math.ceil(peso_gramas / 1000))
    valor_pac = base_pac + (faixas_kg - 1) * 5.0
    return [
        {"id": 1, "nome": "PAC", "transportadora": "Correios", "valor": round(valor_pac, 2), "prazo": "6 a 8 dias úteis"},
        {"id": 2, "nome": "Sedex", "transportadora": "Correios", "valor": round(valor_pac + 22.50, 2), "prazo": "2 a 3 dias úteis"},
        {"id": 3, "nome": ".Package", "transportadora": "Jadlog", "valor": round(max(0, valor_pac - 2.10), 2), "prazo": "5 a 7 dias úteis"},
    ]

def atualizar_estoque_variante(produto, cor, nome_tamanho, delta):
    variantes = variantes_do_produto(produto)
    for variante in variantes:
        mesma_cor = chave_cor(variante.get('cor')) == chave_cor(cor)
        if mesma_cor:
            for tamanho in variante.get('tamanhos', []):
                if tamanho['nome'].casefold() == str(nome_tamanho).casefold():
                    tamanho['estoque'] = max(0, int(tamanho.get('estoque', 0)) + delta)
                    produto.variantes = json.dumps(variantes, ensure_ascii=False)
                    return tamanho['estoque']
    return None

def atualizar_estoque_grade(produto, nome_tamanho, delta):
    grade = grade_do_produto(produto)
    for tamanho in grade:
        if tamanho['nome'].casefold() == str(nome_tamanho).casefold():
            tamanho['estoque'] = max(0, int(tamanho.get('estoque', 0)) + delta)
            produto.grade = json.dumps(grade, ensure_ascii=False)
            return tamanho['estoque']
    return None

def pedido_atual_do_usuario(usuario_id):
    pedido = Pedido.query.filter_by(usuario_id=usuario_id).order_by(Pedido.data_atualizacao.desc(), Pedido.id.desc()).first()
    if pedido and pedido.status in {'ABERTO', 'PAGAMENTO', 'ABANDONADO'}:
        return pedido
    return None

def reativar_pedido_abandonado(pedido, itens):
    reservas = {}
    for item in itens:
        produto = db.session.get(Produto, item.get('id'))
        if not produto:
            return f"O produto {item.get('nome', '')} não está mais cadastrado."
        variante = next((variante for variante in variantes_do_produto(produto) if chave_cor(variante.get('cor')) == chave_cor(item.get('cor'))), None)
        tamanho = next((tamanho for tamanho in (variante or {}).get('tamanhos', []) if tamanho.get('nome', '').casefold() == str(item.get('tamanho', '')).casefold()), None)
        if not tamanho:
            return f"A variação {item.get('nome', '')} ({item.get('cor')}, {item.get('tamanho')}) não está mais disponível."
        quantidade = int(item.get('quantidade') or 0)
        chave = (produto.id, chave_cor(item.get('cor')), str(item.get('tamanho', '')).casefold())
        reserva = reservas.setdefault(chave, {'produto': produto, 'cor': item.get('cor'), 'tamanho': item.get('tamanho'), 'quantidade': 0})
        reserva['quantidade'] += quantidade

    for reserva in reservas.values():
        variante = next((variante for variante in variantes_do_produto(reserva['produto']) if chave_cor(variante.get('cor')) == chave_cor(reserva['cor'])), None)
        tamanho = next((tamanho for tamanho in (variante or {}).get('tamanhos', []) if tamanho.get('nome', '').casefold() == str(reserva['tamanho']).casefold()), None)
        if not tamanho or int(tamanho.get('estoque', 0)) < reserva['quantidade']:
            return f"Estoque insuficiente para {reserva['produto'].nome} ({reserva['cor']}, {reserva['tamanho']}). Atualize a sacola para continuar."

    for reserva in reservas.values():
        atualizar_estoque_variante(reserva['produto'], reserva['cor'], reserva['tamanho'], -reserva['quantidade'])
    pedido.status = 'ABERTO'
    pedido.data_atualizacao = datetime.utcnow()
    return None

def ler_precos_formulario(form, prefixo=''):
    precos = {}
    for tamanho in ('p', 'm', 'g', 'gg'):
        valor = form.get(f'{prefixo}preco_{tamanho}')
        precos[tamanho] = float(valor) if valor not in (None, '') else None
    return precos

# ==========================================
# ROTAS DA LOJA E AUTENTICAÇÃO
# ==========================================
@main_bp.route('/')
def index():
    limpar_carrinhos_abandonados()
    
    nova_visita = Visita(ip=request.remote_addr)
    db.session.add(nova_visita)
    db.session.commit()
    
    email_admin = current_app.config.get('ADMIN_EMAIL')
    senha_admin = current_app.config.get('ADMIN_PASSWORD')
    if Admin.query.count() == 0 and email_admin and senha_admin:
        hashed_admin = generate_password_hash(senha_admin, method='pbkdf2:sha256')
        db.session.add(Admin(email=email_admin, senha=hashed_admin))
        db.session.commit()

    garantir_imagens_site()
    imagens_site = {imagem.chave: imagem.imagem_url for imagem in ImagemSite.query.all()}
    imagens_hero = [
        imagens_site[chave]
        for chave in ('banner_hero', 'banner_hero_2', 'banner_hero_3')
        if imagem_disponivel(imagens_site.get(chave))
    ]

    categoria = request.args.get('categoria', '').strip().casefold()
    produtos = Produto.query.order_by(Produto.promocao.desc(), Produto.nome.asc()).all()
    if categoria:
        categorias_legadas = {
            'conjuntos': {'conjunto-calca-top-estampado', 'conjunto-calca-top-liso', 'short-top', 'short-saia'},
            'leggings': {'calca'},
            'casacos': {'blusas-casacos'},
            'tops': {'top'},
        }
        categorias_aceitas = categorias_legadas.get(categoria, {categoria})
        produtos = [produto for produto in produtos if categoria_para_exibicao(produto) in categorias_aceitas]

    produtos_ordenados = produtos
    produtos_destaque = [produto for produto in produtos_ordenados if produto.promocao]
    produtos_comuns = [produto for produto in produtos_ordenados if not produto.promocao]

    page = request.args.get('page', 1, type=int)
    per_page = 16
    total_paginas = max(1, (len(produtos_comuns) + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_paginas:
        page = total_paginas
    inicio = (page - 1) * per_page
    fim = inicio + per_page
    produtos_paginados = produtos_comuns[inicio:fim]

    return render_template('index.html', 
                           produtos=type('PaginaProdutos', (), {
                               'items': produtos_paginados,
                               'page': page,
                               'has_prev': page > 1,
                               'has_next': page < total_paginas,
                               'prev_num': page - 1,
                               'next_num': page + 1,
                               'iter_pages': lambda *args, **kwargs: range(1, total_paginas + 1),
                           })(),
                           produtos_destaque=produtos_destaque,
                           imagens_site=imagens_site,
                           imagens_hero=imagens_hero,
                           whatsapp_loja_url=link_whatsapp_cliente(current_app.config.get('WHATSAPP_LOJA')),
                           usuario_logado=current_user.is_authenticated,
                           nome_usuario=current_user.nome if current_user.is_authenticated else '',
                           google_login_enabled=current_app.config.get('GOOGLE_LOGIN_ENABLED', False),
                           categoria_atual=categoria)

@main_bp.route('/api/produtos/buscar')
def api_buscar_produtos():
    termo = re.sub(r'\s+', ' ', str(request.args.get('q') or '').strip())
    if len(termo) < 2:
        return jsonify([])

    produtos = Produto.query.filter(
        or_(Produto.nome.ilike(f'%{termo}%'), Produto.codigo.ilike(f'%{termo}%'))
    ).order_by(Produto.promocao.desc(), Produto.nome.asc()).all()
    return jsonify([
        {
            'id': produto.id,
            'codigo': produto.codigo or '-',
            'nome': produto.nome,
            'preco_minimo': produto.preco_minimo,
            'imagem_url': url_for('static', filename=produto.imagem_url) if imagem_disponivel(produto.imagem_url) else '',
            'variantes': variantes_com_cor_hex(variantes_do_produto(produto)),
        }
        for produto in produtos
    ])

@main_bp.route('/api/cadastro', methods=['POST'])
def api_cadastro():
    dados = request.get_json(silent=True) or {}
    nome = re.sub(r'\s+', ' ', str(dados.get('nome') or '').strip())
    whatsapp = str(dados.get('whatsapp') or '').strip()
    whatsapp_normalizado = re.sub(r'\D', '', whatsapp)
    if not nome or not whatsapp_normalizado:
        return jsonify({"sucesso": False, "mensagem": "Informe seu nome e WhatsApp."}), 400
    if len(whatsapp_normalizado) < 10 or len(whatsapp_normalizado) > 15:
        return jsonify({"sucesso": False, "mensagem": "Informe um número de WhatsApp válido."}), 400
    if any(re.sub(r'\D', '', usuario.whatsapp or '') == whatsapp_normalizado for usuario in Usuario.query.all()):
        return jsonify({"sucesso": False, "mensagem": "Este WhatsApp já está cadastrado. Faça login."})

    novo_usuario = Usuario(
        nome=nome,
        email=f'whatsapp+{whatsapp_normalizado}@clientes.leyly.local',
        senha=generate_password_hash(secrets.token_urlsafe(32), method='pbkdf2:sha256'),
        whatsapp=whatsapp_normalizado,
    )
    db.session.add(novo_usuario)
    db.session.commit()
    login_user(novo_usuario)
    return jsonify({"sucesso": True, "mensagem": "Cadastro realizado com sucesso!"})

@main_bp.route('/api/login', methods=['POST'])
def api_login():
    dados = request.get_json(silent=True) or {}
    nome = re.sub(r'\s+', ' ', str(dados.get('nome') or '').strip()).casefold()
    whatsapp = re.sub(r'\D', '', str(dados.get('whatsapp') or ''))
    usuario = next((
        item for item in Usuario.query.all()
        if re.sub(r'\s+', ' ', item.nome.strip()).casefold() == nome
        and re.sub(r'\D', '', item.whatsapp or '') == whatsapp
    ), None) if nome and whatsapp else None
    if usuario:
        login_user(usuario)
        return jsonify({"sucesso": True, "nome": usuario.nome})
    return jsonify({"sucesso": False, "mensagem": "Nome ou WhatsApp incorretos."})

@main_bp.route('/login/google')
def login_google():
    google = current_app.extensions.get('google_oauth')
    if not google:
        flash('O acesso com Google ainda não foi configurado.')
        return redirect(url_for('main.index'))
    if current_app.config.get('IS_RENDER'):
        redirect_uri = url_for('main.login_google_callback', _external=True, _scheme='https')
    else:
        redirect_uri = url_for('main.login_google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@main_bp.route('/login/google/callback')
def login_google_callback():
    google = current_app.extensions.get('google_oauth')
    if not google:
        flash('O acesso com Google ainda não foi configurado.')
        return redirect(url_for('main.index'))

    try:
        token = google.authorize_access_token()
        userinfo = token.get('userinfo') or google.userinfo()
        google_sub = str(userinfo.get('sub') or '').strip()
        email = str(userinfo.get('email') or '').strip().lower()
        if not google_sub or not email or userinfo.get('email_verified') is not True:
            flash('O Google não confirmou um e-mail válido para esta conta.')
            return redirect(url_for('main.index'))

        usuario = Usuario.query.filter_by(google_sub=google_sub).first()
        if not usuario:
            usuario = db.session.query(Usuario).filter(db.func.lower(Usuario.email) == email).first()
            if usuario and usuario.google_sub and usuario.google_sub != google_sub:
                flash('Este e-mail já está vinculado a outra conta Google.')
                return redirect(url_for('main.index'))
            if usuario:
                usuario.google_sub = google_sub
            else:
                usuario = Usuario(
                    nome=str(userinfo.get('name') or email.split('@')[0]).strip(),
                    email=email,
                    senha=generate_password_hash(secrets.token_urlsafe(48), method='pbkdf2:sha256'),
                    google_sub=google_sub,
                )
                db.session.add(usuario)
        db.session.commit()
        login_user(usuario)
        return redirect(url_for('main.index'))
    except IntegrityError:
        db.session.rollback()
        usuario = Usuario.query.filter_by(google_sub=google_sub).first() if 'google_sub' in locals() else None
        if usuario:
            login_user(usuario)
            return redirect(url_for('main.index'))
        flash('Não foi possível vincular esta conta Google. Tente novamente.')
        return redirect(url_for('main.index'))
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Falha no login Google.')
        flash('Não foi possível entrar com Google. Tente novamente.')
        return redirect(url_for('main.index'))

@main_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))

# ==========================================
# ROTAS DO PAINEL ADMIN
# ==========================================
@main_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logado'): return redirect(url_for('main.admin_dashboard'))
    erro = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        admin = Admin.query.filter(db.func.lower(Admin.email) == email).first()
        if admin and check_password_hash(admin.senha, request.form.get('senha')):
            session['admin_logado'] = True
            return redirect(url_for('main.admin_dashboard'))
        erro = "Credenciais administrativas inválidas."
    return render_template('admin_login.html', erro=erro)

@main_bp.route('/admin/logout')
def admin_logout():
    session.pop('admin_logado', None)
    return redirect(url_for('main.admin_login'))

@main_bp.route('/admin')
def admin_dashboard():
    if not session.get('admin_logado'): return redirect(url_for('main.admin_login'))
    return render_template('admin.html', categorias_produto=CATEGORIAS_PRODUTO)

@main_bp.route('/api/admin/admins', methods=['GET', 'POST'])
def api_admin_admins():
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado."}), 403

    if request.method == 'GET':
        administradores = Admin.query.order_by(Admin.email.asc()).all()
        return jsonify([{"id": admin.id, "email": admin.email} for admin in administradores])

    dados = request.get_json(silent=True) or {}
    email = str(dados.get('email', '')).strip().lower()
    senha = str(dados.get('senha', ''))
    if not email or '@' not in email:
        return jsonify({"sucesso": False, "mensagem": "Informe um e-mail válido."}), 400
    if len(senha) < 12:
        return jsonify({"sucesso": False, "mensagem": "A senha precisa ter pelo menos 12 caracteres."}), 400
    if db.session.query(Admin.id).filter(db.func.lower(Admin.email) == email).first():
        return jsonify({"sucesso": False, "mensagem": "Já existe um administrador com esse e-mail."}), 409

    novo_admin = Admin(email=email, senha=generate_password_hash(senha, method='pbkdf2:sha256'))
    db.session.add(novo_admin)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": "Não foi possível criar o administrador."}), 500
    return jsonify({"sucesso": True, "id": novo_admin.id, "email": novo_admin.email}), 201

@main_bp.route('/api/admin/pedidos')
def api_admin_pedidos():
    if not session.get('admin_logado'): return jsonify([])
    limpar_carrinhos_abandonados()
    
    pedidos = Pedido.query.order_by(Pedido.id.asc()).all()
    resultado = []
    for p in pedidos:
        itens_enriquecidos = []
        if p.itens and p.itens != '[]':
            for item in json.loads(p.itens):
                prod = Produto.query.get(item['id'])
                item['codigo'] = prod.codigo if prod else '-'
                imagem_produto = (prod.imagem_url or (prod.imagens[0].imagem_url if prod.imagens else '')) if prod else ''
                if imagem_produto:
                    base_imagem, extensao_imagem = os.path.splitext(imagem_produto)
                    imagem_preview = imagem_produto if extensao_imagem.lower() == '.gif' else f'{base_imagem}.thumb.webp'
                    if not imagem_disponivel(imagem_preview):
                        imagem_preview = imagem_produto
                    item['imagem_url'] = url_for('static', filename=imagem_preview) if imagem_disponivel(imagem_preview) else ''
                else:
                    item['imagem_url'] = ''
                itens_enriquecidos.append(item)

        resultado.append({
            "id": p.id, "cliente": p.nome_cliente or (p.usuario.nome if p.usuario else 'Cliente não identificado'), "whatsapp": p.usuario.whatsapp if p.usuario else None, "whatsapp_url": link_whatsapp_cliente(p.usuario.whatsapp if p.usuario else None), "nome_cliente": p.nome_cliente or (p.usuario.nome if p.usuario else 'Cliente não identificado'), "observacao": p.observacao or '', "endereco": p.endereco, "frete_tipo": p.frete_tipo,
            "status": p.status, "total": p.valor_total, "frete_estimado": p.frete_estimado or 0, "itens": itens_enriquecidos, "atualizado": p.data_atualizacao.strftime('%d/%m %H:%M')
        })
    return jsonify(resultado)

@main_bp.route('/api/admin/pedidos/atualizar-status', methods=['POST'])
def api_admin_atualizar_status_pedido():
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado."}), 403
    dados = request.get_json(silent=True) or {}
    pedido = db.session.get(Pedido, dados.get('id'))
    status_novo = str(dados.get('status') or '').upper()
    status_validos = {'ABERTO', 'PAGAMENTO', 'PAGO', 'SEPARACAO', 'ENVIADO', 'CONCLUIDO', 'ABANDONADO'}
    if not pedido:
        return jsonify({"sucesso": False, "mensagem": "Pedido não encontrado."}), 404
    if pedido.status == 'CANCELADO' or status_novo not in status_validos:
        return jsonify({"sucesso": False, "mensagem": "Status inválido para este pedido."}), 409
    if status_novo in {'PAGO', 'SEPARACAO', 'ENVIADO', 'CONCLUIDO'}:
        itens_pedido = json.loads(pedido.itens or '[]')
        subtotal = sum(float(item.get('preco') or 0) * int(item.get('quantidade') or 0) for item in itens_pedido)
        if subtotal < VALOR_MINIMO_ATACADO:
            return jsonify({"sucesso": False, "mensagem": f"Não é possível confirmar o pedido abaixo do mínimo de R$ {VALOR_MINIMO_ATACADO:,.2f}."}), 409
    pedido.status = status_novo
    pedido.data_atualizacao = datetime.utcnow()
    db.session.commit()
    return jsonify({"sucesso": True})

@main_bp.route('/api/admin/pedidos/editar', methods=['POST'])
def api_admin_editar_pedido():
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado."}), 403
    dados = request.get_json(silent=True) or {}
    pedido = db.session.get(Pedido, dados.get('id'))
    if not pedido:
        return jsonify({"sucesso": False, "mensagem": "Pedido não encontrado."}), 404
    if pedido.status not in STATUS_PEDIDO_EDITAVEIS:
        return jsonify({"sucesso": False, "mensagem": "Este pedido não pode mais ser editado."}), 409

    endereco = dados.get('endereco', pedido.endereco or '')
    frete_tipo = dados.get('frete_tipo', pedido.frete_tipo or '')
    nome_cliente = dados.get('nome_cliente', pedido.nome_cliente or (pedido.usuario.nome if pedido.usuario else ''))
    observacao = dados.get('observacao', pedido.observacao or '')
    quantidades = dados.get('quantidades')
    if not isinstance(endereco, str) or len(endereco) > 255:
        return jsonify({"sucesso": False, "mensagem": "O endereço deve ter no máximo 255 caracteres."}), 400
    if not isinstance(frete_tipo, str) or len(frete_tipo) > 100:
        return jsonify({"sucesso": False, "mensagem": "A forma de envio deve ter no máximo 100 caracteres."}), 400
    if not isinstance(nome_cliente, str) or not nome_cliente.strip() or len(nome_cliente.strip()) > 100:
        return jsonify({"sucesso": False, "mensagem": "Informe o nome do cliente com até 100 caracteres."}), 400
    if not isinstance(observacao, str) or len(observacao) > 2000:
        return jsonify({"sucesso": False, "mensagem": "A observação deve ter no máximo 2000 caracteres."}), 400

    itens_antigos = json.loads(pedido.itens or '[]')
    itens_novos = [dict(item) for item in itens_antigos]
    alteracoes_estoque = {}
    if quantidades is not None:
        if not isinstance(quantidades, list) or len(quantidades) != len(itens_antigos):
            return jsonify({"sucesso": False, "mensagem": "A lista de quantidades não corresponde aos itens do pedido."}), 400
        try:
            quantidades = [int(quantidade) for quantidade in quantidades]
        except (TypeError, ValueError):
            return jsonify({"sucesso": False, "mensagem": "Informe quantidades inteiras válidas."}), 400
        if any(quantidade < 0 for quantidade in quantidades) or not any(quantidades):
            return jsonify({"sucesso": False, "mensagem": "Mantenha ao menos um item e não use quantidades negativas."}), 400

        for item, quantidade_nova in zip(itens_novos, quantidades):
            item['quantidade'] = quantidade_nova
        subtotal_novo = sum(float(item.get('preco') or 0) * int(item.get('quantidade') or 0) for item in itens_novos)
        if pedido.status in {'PAGO', 'SEPARACAO'} and subtotal_novo < VALOR_MINIMO_ATACADO:
            return jsonify({"sucesso": False, "mensagem": f"O pedido confirmado não pode ficar abaixo do mínimo de R$ {VALOR_MINIMO_ATACADO:,.2f}."}), 409

        for indice, (item, quantidade_nova) in enumerate(zip(itens_antigos, quantidades)):
            quantidade_antiga = int(item.get('quantidade') or 0)
            delta = quantidade_nova - quantidade_antiga
            if delta:
                produto = db.session.get(Produto, item.get('id'))
                if not produto:
                    return jsonify({"sucesso": False, "mensagem": f"O produto {item.get('nome', '')} não está mais cadastrado."}), 409
                variante = next((variante for variante in variantes_do_produto(produto) if chave_cor(variante.get('cor')) == chave_cor(item.get('cor'))), None)
                tamanho = next((tamanho for tamanho in (variante or {}).get('tamanhos', []) if tamanho.get('nome', '').casefold() == str(item.get('tamanho', '')).casefold()), None)
                if not tamanho:
                    return jsonify({"sucesso": False, "mensagem": f"A variação {item.get('nome', '')} ({item.get('cor')}, {item.get('tamanho')}) não está mais disponível no catálogo."}), 409
                chave = (produto.id, chave_cor(item.get('cor')), str(item.get('tamanho', '')).casefold())
                alteracao = alteracoes_estoque.setdefault(chave, {'produto': produto, 'cor': item.get('cor'), 'tamanho': item.get('tamanho'), 'delta': 0})
                alteracao['delta'] += delta
            itens_novos[indice]['quantidade'] = quantidade_nova

        if all(alteracao['delta'] == 0 for alteracao in alteracoes_estoque.values()):
            alteracoes_estoque.clear()
        for alteracao in alteracoes_estoque.values():
            if alteracao['delta'] <= 0:
                continue
            variante = next((variante for variante in variantes_do_produto(alteracao['produto']) if chave_cor(variante.get('cor')) == chave_cor(alteracao['cor'])), None)
            tamanho = next((tamanho for tamanho in (variante or {}).get('tamanhos', []) if tamanho.get('nome', '').casefold() == str(alteracao['tamanho']).casefold()), None)
            if not tamanho or int(tamanho.get('estoque', 0)) < alteracao['delta']:
                return jsonify({"sucesso": False, "mensagem": f"Estoque insuficiente para {alteracao['produto'].nome} ({alteracao['cor']}, {alteracao['tamanho']})."}), 409

    try:
        for alteracao in alteracoes_estoque.values():
            atualizar_estoque_variante(alteracao['produto'], alteracao['cor'], alteracao['tamanho'], -alteracao['delta'])
        if quantidades is not None:
            itens_novos = [item for item in itens_novos if int(item.get('quantidade') or 0) > 0]
            subtotal_antigo = sum(float(item.get('preco') or 0) * int(item.get('quantidade') or 0) for item in itens_antigos)
            subtotal_novo = sum(float(item.get('preco') or 0) * int(item.get('quantidade') or 0) for item in itens_novos)
            frete_atual = max(0, float(pedido.frete_estimado or 0))
            pedido.itens = json.dumps(itens_novos, ensure_ascii=False)
            pedido.valor_total = round(subtotal_novo, 2)
            pedido.frete_estimado = round(frete_atual, 2)
        pedido.endereco = endereco.strip() or None
        pedido.frete_tipo = frete_tipo.strip() or 'Não selecionado'
        pedido.nome_cliente = nome_cliente.strip()
        pedido.observacao = observacao.strip() or None
        pedido.data_atualizacao = datetime.utcnow()
        db.session.commit()
    except (TypeError, ValueError) as erro:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": str(erro)}), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Falha ao editar pedido %s.', pedido.id)
        return jsonify({"sucesso": False, "mensagem": "Não foi possível salvar as alterações do pedido."}), 500

    return jsonify({"sucesso": True, "total": pedido.valor_total})

@main_bp.route('/api/admin/pedidos/cancelar', methods=['POST'])
def api_admin_cancelar_pedido():
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado."}), 403
    dados = request.get_json(silent=True) or {}
    pedido = db.session.get(Pedido, dados.get('id'))
    if not pedido:
        return jsonify({"sucesso": False, "mensagem": "Pedido não encontrado."}), 404
    if pedido.status == 'CANCELADO':
        return jsonify({"sucesso": False, "mensagem": "Este pedido já foi cancelado."}), 409
    if pedido.status in {'ENVIADO', 'CONCLUIDO'}:
        return jsonify({"sucesso": False, "mensagem": "Não é possível cancelar um pedido enviado ou concluído."}), 409
    if pedido.status not in STATUS_PEDIDO_EDITAVEIS:
        return jsonify({"sucesso": False, "mensagem": "Este pedido não pode ser cancelado."}), 409

    try:
        if pedido.status in STATUS_PEDIDO_EDITAVEIS:
            for item in json.loads(pedido.itens or '[]'):
                produto = db.session.get(Produto, item.get('id'))
                if produto and atualizar_estoque_variante(produto, item.get('cor'), item.get('tamanho'), int(item.get('quantidade') or 0)) is None:
                    raise ValueError(f"Não foi possível devolver ao estoque {item.get('nome', 'um item')} ({item.get('cor')}, {item.get('tamanho')}).")
        pedido.status = 'CANCELADO'
        pedido.data_atualizacao = datetime.utcnow()
        db.session.commit()
    except (TypeError, ValueError, json.JSONDecodeError) as erro:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": str(erro)}), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Falha ao cancelar pedido %s.', pedido.id)
        return jsonify({"sucesso": False, "mensagem": "Não foi possível cancelar o pedido."}), 500

    mensagem = 'Pedido cancelado.'
    if pedido.valor_total:
        mensagem += ' Se o pagamento foi recebido, faça o estorno fora do sistema.'
    return jsonify({"sucesso": True, "mensagem": mensagem})

@main_bp.route('/api/admin/produtos', methods=['GET'])
def api_admin_produtos():
    if not session.get('admin_logado'): return jsonify([])
    produtos = Produto.query.all()
    return jsonify([{
        "id": p.id, "codigo": p.codigo, "nome": p.nome, "categoria": categoria_para_exibicao(p), "categoria_manual": bool(p.categoria), "preco": p.preco,
        "precos": {tamanho: preco_tamanho(p, tamanho) for tamanho in ('P', 'M', 'G', 'GG')}, "grade": grade_do_produto(p), "cores": p.cores_config, "variantes": variantes_com_cor_hex(variantes_do_produto(p)), "imagem_url": p.imagem_url,
        "imagens": [{"id": imagem.id, "url": imagem.imagem_url} for imagem in p.imagens],
        "promocao": p.promocao,
        "p": p.estoque_p, "m": p.estoque_m, "g": p.estoque_g, "gg": p.estoque_gg
    } for p in produtos])

@main_bp.route('/api/admin/produtos/<int:produto_id>/promocao', methods=['POST'])
def api_admin_definir_promocao(produto_id):
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado."}), 403
    produto = db.session.get(Produto, produto_id)
    if not produto:
        return jsonify({"sucesso": False, "mensagem": "Produto não encontrado."}), 404
    dados = request.get_json(silent=True) or {}
    promocao = dados.get('promocao')
    if not isinstance(promocao, bool):
        return jsonify({"sucesso": False, "mensagem": "Seleção de promoção inválida."}), 400
    produto.promocao = promocao
    db.session.commit()
    return jsonify({"sucesso": True, "promocao": produto.promocao})

@main_bp.route('/api/admin/importar-estoque', methods=['POST'])
def api_admin_importar_estoque():
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado."}), 401

    arquivo = request.files.get('arquivo') or request.files.get('file') or request.files.get('txt')
    if arquivo is None or not getattr(arquivo, 'filename', None):
        return jsonify({"sucesso": False, "mensagem": "Selecione um arquivo .txt para importar."}), 400

    try:
        from scripts.importar_estoque import executar_importacao
        resultado = executar_importacao(
            app=current_app._get_current_object(),
            aplicar=True,
            arquivo=arquivo,
            gerar_referencia_ausente=True,
        )
    except Exception as erro:
        return jsonify({"sucesso": False, "mensagem": f"Erro ao importar estoque: {erro}"}), 500

    if not resultado.get('sucesso'):
        return jsonify({
            "sucesso": False,
            "mensagem": resultado.get('mensagem', 'Não foi possível importar o estoque.'),
            "problemas": resultado.get('problemas', []),
        }), 400

    return jsonify({
        "sucesso": True,
        "mensagem": resultado.get('mensagem', 'Importação concluída.'),
        "produtos": resultado.get('produtos', 0),
        "importada": resultado.get('importada', True),
    })

@main_bp.route('/api/admin/imagens-site')
def api_admin_imagens_site():
    if not session.get('admin_logado'):
        return jsonify([])
    garantir_imagens_site()
    return jsonify([{'chave': imagem.chave, 'nome': imagem.nome, 'imagem_url': imagem.imagem_url} for imagem in ImagemSite.query.order_by(ImagemSite.id).all()])

@main_bp.route('/api/admin/imagens-site/<chave>', methods=['POST'])
def api_admin_atualizar_imagem_site(chave):
    if not session.get('admin_logado'):
        return jsonify({'sucesso': False, 'mensagem': 'Não autorizado.'}), 401
    imagem = ImagemSite.query.filter_by(chave=chave).first()
    arquivo = request.files.get('imagem')
    if not imagem or not arquivo or not arquivo.filename:
        return jsonify({'sucesso': False, 'mensagem': 'Selecione uma imagem.'})
    try:
        imagem.imagem_url = salvar_arquivo_imagem(arquivo)
        db.session.commit()
        return jsonify({'sucesso': True, 'imagem_url': imagem.imagem_url})
    except (ValueError, OSError) as erro:
        db.session.rollback()
        return jsonify({'sucesso': False, 'mensagem': str(erro)})

@main_bp.route('/api/admin/produtos/atualizar', methods=['POST'])
def api_admin_atualizar_estoque():
    if not session.get('admin_logado'): return jsonify({"sucesso": False})
    dados = request.get_json()
    prod = Produto.query.get(dados.get('id'))
    if prod:
        prod.estoque_p = int(dados.get('p') or 0); prod.estoque_m = int(dados.get('m') or 0); prod.estoque_g = int(dados.get('g') or 0); prod.estoque_gg = int(dados.get('gg') or 0)
        db.session.commit()
        return jsonify({"sucesso": True})
    return jsonify({"sucesso": False})

@main_bp.route('/api/admin/produtos/cadastrar', methods=['POST'])
def api_admin_cadastrar_produto():
    if not session.get('admin_logado'): return jsonify({"sucesso": False})
    try:
        codigo = request.form.get('codigo', '').strip()
        nome = request.form.get('nome', '').strip()
        if referencia_em_uso(codigo):
            return jsonify({"sucesso": False, "mensagem": f"A referência {codigo} já está cadastrada."}), 409
        arquivos = [arquivo for arquivo in request.files.getlist('imagens') if arquivo and arquivo.filename]
        precos = ler_precos_formulario(request.form)
        try:
            grade_personalizada = json.loads(request.form.get('grade', '[]'))
        except json.JSONDecodeError:
            grade_personalizada = []
        try:
            cores_personalizadas = json.loads(request.form.get('cores', '[]'))
        except json.JSONDecodeError:
            cores_personalizadas = []
        try:
            variantes_personalizadas = json.loads(request.form.get('variantes', '[]'))
        except json.JSONDecodeError:
            variantes_personalizadas = []
        preco_unico = request.form.get('preco')
        quantidades = [int(request.form.get(tamanho) or 0) for tamanho in ('p', 'm', 'g', 'gg')]
        if not codigo or not nome or not arquivos or not variantes_personalizadas:
            return jsonify({"sucesso": False, "mensagem": "Código, nome e pelo menos uma foto são obrigatórios."})
        categoria = categoria_selecionada(request.form.get('categoria'), nome)
        tamanhos_personalizados = [tamanho for variante in variantes_personalizadas for tamanho in variante.get('tamanhos', [])]
        precos_grade = [float(tamanho.get('preco')) for tamanho in tamanhos_personalizados if tamanho.get('preco') not in (None, '')]
        if not preco_unico and (not tamanhos_personalizados or len(precos_grade) != len(tamanhos_personalizados)):
            return jsonify({"sucesso": False, "mensagem": "Informe um preço único ou o preço de cada tamanho."})
        preco_base = float(preco_unico or precos_grade[0])
        if preco_unico:
            precos = {'p': None, 'm': None, 'g': None, 'gg': None}
        variantes_normalizadas = []
        for variante in variantes_personalizadas:
            cor = normalizar_cor(variante.get('cor'))
            tamanhos = [{'nome': str(t.get('nome', '')).strip(), 'estoque': max(0, int(t.get('estoque', 0))), 'preco': float(t.get('preco') or preco_base)} for t in variante.get('tamanhos', []) if str(t.get('nome', '')).strip()]
            if tamanhos and cor:
                variantes_normalizadas.append({'cor': cor, 'tamanhos': tamanhos})
        if not variantes_normalizadas:
            return jsonify({"sucesso": False, "mensagem": "Adicione pelo menos uma cor e um tamanho válido."})
        cores_normalizadas = [cor for cor in (normalizar_cor(item) for item in cores_personalizadas) if cor]
        grade_normalizada = variantes_normalizadas[0]['tamanhos']
        novo_produto = Produto(codigo=codigo, nome=nome, categoria=categoria, preco=preco_base, preco_p=precos['p'], preco_m=precos['m'], preco_g=precos['g'], preco_gg=precos['gg'], grade=json.dumps(grade_normalizada, ensure_ascii=False), cores=json.dumps(cores_normalizadas), variantes=json.dumps(variantes_normalizadas, ensure_ascii=False), etiqueta='NOVO', imagem_url='img/default.jpg', estoque_p=quantidades[0], estoque_m=quantidades[1], estoque_g=quantidades[2], estoque_gg=quantidades[3])
        db.session.add(novo_produto)
        salvar_imagens_produto(novo_produto, arquivos)
        db.session.commit()
        return jsonify({"sucesso": True})
    except ValueError as erro:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": str(erro)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": "Esta referência já foi cadastrada. Atualize a lista de estoque."}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": str(e)})

@main_bp.route('/api/admin/produtos/editar/<int:id>', methods=['POST'])
def api_admin_editar_produto(id):
    if not session.get('admin_logado'): return jsonify({"sucesso": False})
    try:
        prod = Produto.query.get(id)
        if not prod: return jsonify({"sucesso": False, "mensagem": "Produto não encontrado."})

        preco_base_anterior = float(prod.preco or 0)
        codigo_novo = request.form.get('codigo', prod.codigo).strip()
        if referencia_em_uso(codigo_novo, ignorar_id=prod.id):
            return jsonify({"sucesso": False, "mensagem": f"A referência {codigo_novo} já está cadastrada em outro produto."}), 409
        prod.codigo = codigo_novo
        prod.nome = request.form.get('nome', prod.nome)
        categoria_enviada = request.form.get('categoria')
        if categoria_enviada is not None:
            prod.categoria = categoria_selecionada(categoria_enviada, prod.nome)
        if request.form.get('preco'):
            prod.preco = float(request.form.get('preco'))
        precos = ler_precos_formulario(request.form)
        for tamanho, valor in precos.items():
            setattr(prod, f'preco_{tamanho}', valor)
        if request.form.get('grade'):
            prod.grade = request.form.get('grade')
        if request.form.get('cores') is not None:
            cores_editadas = [cor for cor in (normalizar_cor(item) for item in json.loads(request.form.get('cores', '[]'))) if cor]
            prod.cores = json.dumps(cores_editadas, ensure_ascii=False)
        if request.form.get('variantes'):
            variantes_editadas = json.loads(request.form.get('variantes'))
            variantes_editadas = [
                {
                    'cor': cor,
                    'tamanhos': [
                        {
                            **tamanho,
                            'preco': (
                                float(prod.preco)
                                if tamanho.get('preco') in (None, '') or float(tamanho['preco']) == preco_base_anterior
                                else float(tamanho['preco'])
                            ),
                        }
                        for tamanho in variante.get('tamanhos', [])
                    ],
                }
                for variante in variantes_editadas
                if (cor := normalizar_cor(variante.get('cor')))
            ]
            prod.variantes = json.dumps(variantes_editadas, ensure_ascii=False)
            prod.grade = json.dumps(variantes_editadas[0].get('tamanhos', []) if variantes_editadas else [], ensure_ascii=False)

        capa = request.files.get('capa')
        if capa and capa.filename:
            prod.imagem_url = salvar_arquivo_imagem(capa)
            
        salvar_imagens_produto(prod, request.files.getlist('imagens'))

        prod.estoque_p = int(request.form.get('p', prod.estoque_p))
        prod.estoque_m = int(request.form.get('m', prod.estoque_m))
        prod.estoque_g = int(request.form.get('g', prod.estoque_g))
        prod.estoque_gg = int(request.form.get('gg', prod.estoque_gg))

        db.session.commit()
        return jsonify({"sucesso": True})
    except ValueError as erro:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": str(erro)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": "Esta referência já está cadastrada em outro produto."}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": str(e)})

@main_bp.route('/api/admin/produtos/<int:produto_id>/imagens/<int:imagem_id>/excluir', methods=['POST'])
def api_admin_excluir_imagem_produto(produto_id, imagem_id):
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado."}), 401
    produto = Produto.query.get(produto_id)
    if not produto:
        return jsonify({"sucesso": False, "mensagem": "Produto não encontrado."}), 404
    imagem = ProdutoImagem.query.filter_by(id=imagem_id, produto_id=produto_id).first()
    if not imagem:
        return jsonify({"sucesso": False, "mensagem": "Imagem não encontrada."}), 404

    if produto.imagem_url == imagem.imagem_url:
        restantes = [item for item in produto.imagens if item.id != imagem_id]
        produto.imagem_url = restantes[0].imagem_url if restantes else 'img/default.jpg'

    db.session.delete(imagem)
    db.session.commit()
    return jsonify({"sucesso": True, "imagem_url": produto.imagem_url})


@main_bp.route('/api/admin/produtos/excluir/<int:id>', methods=['POST'])
def api_admin_excluir_produto(id):
    if not session.get('admin_logado'): return jsonify({"sucesso": False})
    try:
        prod = Produto.query.get(id)
        if prod:
            db.session.delete(prod)
            db.session.commit()
        return jsonify({"sucesso": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": str(e)})

@main_bp.route('/api/admin/dashboard')
def api_admin_dashboard():
    if not session.get('admin_logado'): return jsonify({})
    limpar_carrinhos_abandonados()
    
    pedidos = Pedido.query.all()
    fat = 0; qtd_vendas = 0; pecas = 0; abandonos = 0; abertos = 0; fretes = {}; valor_perdido = 0
    produtos_vendidos = {}
    clientes_compras = {}

    for p in pedidos:
        if p.status in ['PAGO', 'SEPARACAO', 'CONCLUIDO']:
            fat += p.valor_total
            qtd_vendas += 1
            nome_cliente = p.usuario.nome if p.usuario else 'Cliente não identificado'
            clientes_compras[nome_cliente] = clientes_compras.get(nome_cliente, 0) + 1
            if p.itens and p.itens != '[]':
                for item in json.loads(p.itens):
                    pecas += item['quantidade']
                    nome_base = item['nome']
                    produtos_vendidos[nome_base] = produtos_vendidos.get(nome_base, 0) + item['quantidade']
            tipo_f = p.frete_tipo or 'Não Selecionado'
            fretes[tipo_f] = fretes.get(tipo_f, 0) + 1
        elif p.status == 'ABANDONADO': 
            abandonos += 1
            valor_perdido += p.valor_total
        elif p.status in ['ABERTO', 'PAGAMENTO']: 
            abertos += 1
            
    total_iniciados = abandonos + abertos + qtd_vendas
    taxa_abandono = (abandonos / total_iniciados * 100) if total_iniciados > 0 else 0
    ticket_medio = (fat / qtd_vendas) if qtd_vendas > 0 else 0
    top_produtos = sorted(produtos_vendidos.items(), key=lambda x: x[1], reverse=True)[:5]
    top_clientes = sorted(clientes_compras.items(), key=lambda x: x[1], reverse=True)[:5]
    
    prod_risco = Produto.query.filter(or_(Produto.estoque_p <= 5, Produto.estoque_m <= 5, Produto.estoque_g <= 5, Produto.estoque_gg <= 5)).all()
    risco_ruptura = [{"nome": pr.nome, "estoque": f"P:{pr.estoque_p} M:{pr.estoque_m} G:{pr.estoque_g} GG:{pr.estoque_gg}"} for pr in prod_risco]

    return jsonify({
        "kpis": {"faturamento": fat, "ticket_medio": ticket_medio, "pecas_vendidas": pecas, "taxa_abandono": taxa_abandono, "valor_perdido": valor_perdido},
        "graficos": {"produtos_labels": [x[0][:15]+"..." for x in top_produtos], "produtos_data": [x[1] for x in top_produtos], "clientes_labels": [x[0][:18]+"..." for x in top_clientes], "clientes_data": [x[1] for x in top_clientes], "fretes_labels": list(fretes.keys()), "fretes_data": list(fretes.values())},
        "risco_ruptura": risco_ruptura
    })

@main_bp.route('/api/admin/relatorios')
def api_admin_relatorios():
    if not session.get('admin_logado'): return jsonify({})
    hoje = datetime.utcnow().date()
    datas_labels = [(hoje - timedelta(days=i)).strftime('%d/%m') for i in range(6, -1, -1)]
    
    acessos_data = [0] * 7
    visitas = Visita.query.filter(Visita.data_visita >= datetime.utcnow() - timedelta(days=7)).all()
    for v in visitas:
        dia_str = v.data_visita.strftime('%d/%m')
        if dia_str in datas_labels: acessos_data[datas_labels.index(dia_str)] += 1
            
    vendas_data = [0] * 7
    pedidos = Pedido.query.filter(Pedido.status.in_(['PAGO', 'SEPARACAO', 'CONCLUIDO']), Pedido.data_atualizacao >= datetime.utcnow() - timedelta(days=7)).all()
    for p in pedidos:
        dia_str = p.data_atualizacao.strftime('%d/%m')
        if dia_str in datas_labels: vendas_data[datas_labels.index(dia_str)] += 1

    return jsonify({"labels": datas_labels, "acessos": acessos_data, "vendas": vendas_data})

@main_bp.route('/api/admin/marketing')
def api_admin_marketing():
    if not session.get('admin_logado'): return jsonify({})
    hoje = datetime.utcnow()
    limite_30d = hoje - timedelta(days=30)
    
    visitas = Visita.query.filter(Visita.data_visita >= limite_30d).count()
    pedidos_iniciados = Pedido.query.filter(Pedido.data_atualizacao >= limite_30d).count()
    pedidos_pagos = Pedido.query.filter(Pedido.status.in_(['PAGO', 'SEPARACAO', 'CONCLUIDO']), Pedido.data_atualizacao >= limite_30d).count()
    taxa_conversao = (pedidos_pagos / visitas * 100) if visitas > 0 else 0
    
    abandonados_db = Pedido.query.filter(Pedido.status == 'ABANDONADO', Pedido.data_atualizacao >= limite_30d).all()
    prod_abandonados = {}
    for p in abandonados_db:
        if p.itens and p.itens != '[]':
            for item in json.loads(p.itens):
                nome = item['nome']
                prod_abandonados[nome] = prod_abandonados.get(nome, 0) + item['quantidade']
    
    top_abandonados = sorted(prod_abandonados.items(), key=lambda x: x[1], reverse=True)[:5]
    usuarios_marketing = Usuario.query.order_by(Usuario.nome.asc()).all()
    return jsonify({
        "funil": {"visitas": visitas, "iniciados": pedidos_iniciados, "pagos": pedidos_pagos},
        "conversao": taxa_conversao,
        "top_abandonados": [{"nome": x[0], "qtd": x[1]} for x in top_abandonados],
        "usuarios": [{"id": u.id, "nome": u.nome, "whatsapp": u.whatsapp or "Não informado", "email": u.email} for u in usuarios_marketing]
    })

@main_bp.route('/api/admin/usuarios')
def api_admin_usuarios():
    if not session.get('admin_logado'): return jsonify([])
    usuarios = Usuario.query.order_by(Usuario.nome.asc()).all()
    return jsonify([{
        "id": u.id,
        "nome": u.nome,
        "email": u.email,
        "whatsapp": u.whatsapp or "Não informado",
        "whatsapp_url": link_whatsapp_cliente(u.whatsapp),
        "especial": u.cliente_especial,
        "pedidos": sum(1 for pedido in u.pedidos if pedido.status in ['PAGO', 'SEPARACAO', 'CONCLUIDO'])
    } for u in usuarios])

@main_bp.route('/api/admin/usuarios/<int:usuario_id>/especial', methods=['POST'])
def api_admin_marcar_usuario_especial(usuario_id):
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado"}), 403
    usuario = Usuario.query.get(usuario_id)
    if not usuario:
        return jsonify({"sucesso": False, "mensagem": "Usuário não encontrado"}), 404
    dados = request.get_json(silent=True) or {}
    usuario.cliente_especial = bool(dados.get('especial'))
    db.session.commit()
    return jsonify({"sucesso": True, "especial": usuario.cliente_especial})

@main_bp.route('/api/admin/gerar-etiqueta/<int:pedido_id>')
def api_gerar_etiqueta(pedido_id):
    if not session.get('admin_logado'): return jsonify({"sucesso": False, "mensagem": "Não autorizado"})
    pedido = Pedido.query.get(pedido_id)
    if not pedido: return jsonify({"sucesso": False, "mensagem": "Pedido não encontrado"})
    if pedido.status not in ['PAGO', 'SEPARACAO', 'CONCLUIDO']: return jsonify({"sucesso": False, "mensagem": "Etiqueta disponível apenas para pedidos confirmados."})
    url_pdf_gerado = f"https://sua-api-de-frete.com/etiquetas/print_pedido_{pedido.id}.pdf"
    return jsonify({"sucesso": True, "url_etiqueta": url_pdf_gerado})

# ==========================================
# CHECKOUT E VALIDAÇÃO DE ESTOQUE
# ==========================================
@main_bp.route('/api/carrinho/sync', methods=['POST'])
@login_required
def sync_carrinho():
    limpar_carrinhos_abandonados()
    dados = request.get_json(silent=True) or {}
    novo_carrinho = dados.get('carrinho', [])
    frete_tipo = dados.get('frete_tipo', 'Não selecionado')
    valor_frete = float(dados.get('frete', 0))
    if frete_tipo == 'Excursão':
        valor_frete = VALOR_FRETE_EXCURSAO
    elif frete_tipo == 'Retirada em Surubim':
        valor_frete = 0
    observacao = dados.get('observacao', '')
    if not isinstance(observacao, str) or len(observacao) > 2000:
        return jsonify({"sucesso": False, "mensagem": "A observação deve ter no máximo 2000 caracteres."}), 400
    endereco_envio = dados.get('endereco') or session.get('endereco_envio_selecionado', '')

    pedido = pedido_atual_do_usuario(current_user.id)

    if pedido and pedido.status in ['ABERTO', 'PAGAMENTO'] and pedido.itens != '[]':
        itens_antigos = json.loads(pedido.itens)
        for item in itens_antigos:
            prod = Produto.query.get(item['id'])
            if prod:
                atualizar_estoque_variante(prod, item.get('cor'), item['tamanho'], item['quantidade'])
    
    if novo_carrinho:
        for item in novo_carrinho:
            prod = db.session.get(Produto, item.get('id'))
            if not prod:
                db.session.rollback()
                return jsonify({"sucesso": False, "mensagem": f"O produto '{item.get('nome', 'selecionado')}' foi removido do catálogo."}), 409

            try:
                quantidade = int(item.get('quantidade', 0))
            except (TypeError, ValueError):
                quantidade = 0
            if quantidade <= 0:
                db.session.rollback()
                return jsonify({"sucesso": False, "mensagem": "A quantidade de um produto é inválida."}), 400
            
            variante_configurada = next((variante for variante in variantes_do_produto(prod) if chave_cor(variante.get('cor')) == chave_cor(item.get('cor'))), None)
            tamanho_configurado = next((tamanho for tamanho in (variante_configurada or {}).get('tamanhos', []) if tamanho['nome'].casefold() == str(item['tamanho']).casefold()), None)
            estoque_disp = int(tamanho_configurado.get('estoque', 0)) if tamanho_configurado else 0
            preco_unitario = float(tamanho_configurado.get('preco') or 0) if tamanho_configurado else 0

            if preco_unitario <= 0:
                db.session.rollback()
                return jsonify({"sucesso": False, "mensagem": f"O produto '{prod.nome}' está sem preço. Atualize o preço no estoque antes de continuar."}), 400
            
            if quantidade > estoque_disp:
                db.session.rollback()
                return jsonify({
                    "sucesso": False, 
                    "mensagem": f"O item '{prod.nome}' (Tam: {item['tamanho'].upper()}) esgotou ou não possui a quantidade desejada. Restam {estoque_disp} unidades no momento."
                }), 409

    if not novo_carrinho and pedido:
        pedido.itens = '[]'
        pedido.valor_total = 0
        pedido.frete_estimado = 0
        pedido.observacao = None
        db.session.commit()
        return jsonify({"sucesso": True})

    if not pedido and novo_carrinho:
        pedido = Pedido(usuario_id=current_user.id, status='ABERTO')
        db.session.add(pedido)

    if novo_carrinho:
        carrinho_ajustado = []
        for item in novo_carrinho:
            prod = db.session.get(Produto, item['id'])
            variante_configurada = next(variante for variante in variantes_do_produto(prod) if chave_cor(variante.get('cor')) == chave_cor(item.get('cor')))
            tamanho_configurado = next(tamanho for tamanho in variante_configurada.get('tamanhos', []) if tamanho['nome'].casefold() == str(item['tamanho']).casefold())
            quantidade = int(item['quantidade'])
            preco_unitario = float(tamanho_configurado['preco'])
            carrinho_ajustado.append({**item, 'preco': preco_unitario})

        for item in novo_carrinho:
            prod = db.session.get(Produto, item['id'])
            quantidade = int(item['quantidade'])
            atualizar_estoque_variante(prod, item.get('cor'), item['tamanho'], -quantidade)

        pedido.itens = json.dumps(carrinho_ajustado)
        subtotal_centavos = sum(round(float(item['preco']) * 100) * int(item['quantidade']) for item in carrinho_ajustado)
        pedido.valor_total = subtotal_centavos / 100
        pedido.frete_estimado = round(valor_frete * 100) / 100
        pedido.frete_tipo = frete_tipo
        pedido.observacao = observacao.strip() or None
        if endereco_envio: pedido.endereco = endereco_envio
        pedido.status = 'ABERTO'
        pedido.data_atualizacao = datetime.utcnow()
        db.session.commit()

    return jsonify({"sucesso": True})

@main_bp.route('/api/carrinho', methods=['GET'])
@login_required
def api_carrinho():
    limpar_carrinhos_abandonados()
    pedido = pedido_atual_do_usuario(current_user.id)
    if not pedido or not pedido.itens or pedido.itens == '[]':
        return jsonify({"sucesso": True, "carrinho": [], "frete": 0, "frete_tipo": 'Não selecionado', "endereco": '', "status": None})

    try:
        itens = json.loads(pedido.itens)
    except (TypeError, json.JSONDecodeError):
        return jsonify({"sucesso": False, "mensagem": "Não foi possível recuperar os itens salvos na sacola."}), 500
    for item in itens:
        produto = db.session.get(Produto, item.get('id'))
        variante = next((variante for variante in variantes_do_produto(produto) if chave_cor(variante.get('cor')) == chave_cor(item.get('cor'))), None) if produto else None
        tamanho = next((tamanho for tamanho in (variante or {}).get('tamanhos', []) if tamanho.get('nome', '').casefold() == str(item.get('tamanho', '')).casefold()), None)
        if tamanho:
            estoque = int(tamanho.get('estoque', 0))
            if pedido.status in {'ABERTO', 'PAGAMENTO'}:
                estoque += int(item.get('quantidade') or 0)
            item['estoqueMax'] = estoque
    subtotal = sum(float(item.get('preco') or 0) * int(item.get('quantidade') or 0) for item in itens)
    return jsonify({
        "sucesso": True,
        "carrinho": itens,
        "frete": max(0, round(float(pedido.frete_estimado or 0), 2)),
        "frete_tipo": pedido.frete_tipo or 'Não selecionado',
        "endereco": pedido.endereco or '',
        "observacao": pedido.observacao or '',
        "status": pedido.status,
    })

@main_bp.route('/api/carrinho/observacao', methods=['POST'])
@login_required
def salvar_observacao_carrinho():
    dados = request.get_json(silent=True) or {}
    observacao = dados.get('observacao', '')
    if not isinstance(observacao, str) or len(observacao) > 2000:
        return jsonify({"sucesso": False, "mensagem": "A observação deve ter no máximo 2000 caracteres."}), 400
    pedido = pedido_atual_do_usuario(current_user.id)
    if pedido and pedido.status in {'ABERTO', 'PAGAMENTO'} and pedido.itens != '[]':
        pedido.observacao = observacao.strip() or None
        db.session.commit()
    return jsonify({"sucesso": True})

@main_bp.route('/calcular-frete', methods=['POST'])
def calcular_frete():
    if not current_user.is_authenticated:
        return jsonify({"sucesso": False, "mensagem": "Faça login para calcular o frete."}), 401
    data = request.get_json(silent=True) or {}
    cep_destino = re.sub(r'\D', '', str(data.get('cep', '')))
    cep_origem = re.sub(r'\D', '', str(current_app.config['CEP_ORIGEM']))
    if len(cep_destino) != 8 or len(cep_origem) != 8:
        return jsonify({"sucesso": False, "mensagem": "CEP de origem ou destino inválido."}), 400
    try:
        peso_gramas = peso_total_carrinho(data.get('carrinho', []), current_app.config['PESO_PRODUTO_GRAMAS'])
    except ValueError as erro:
        return jsonify({"sucesso": False, "mensagem": str(erro)}), 400

    try:
        origem_resposta = requests.get(f"https://viacep.com.br/ws/{cep_origem}/json/", timeout=8)
        destino_resposta = requests.get(f"https://viacep.com.br/ws/{cep_destino}/json/", timeout=8)
        origem = origem_resposta.json() if origem_resposta.status_code == 200 else {}
        destino = destino_resposta.json() if destino_resposta.status_code == 200 else {}
    except (requests.RequestException, ValueError):
        return jsonify({"sucesso": False, "mensagem": "Não foi possível consultar os CEPs. Tente novamente."}), 502

    if origem.get('erro') or not origem.get('uf'):
        return jsonify({"sucesso": False, "mensagem": "O CEP de origem configurado é inválido."}), 500
    if destino.get('erro') or not destino.get('uf'):
        return jsonify({"sucesso": False, "mensagem": "CEP de destino não encontrado."}), 400

    endereco_via_cep = f"{destino.get('logradouro', '')}, {destino.get('bairro', '')} - {destino.get('localidade', '')}/{destino.get('uf')} - CEP: {cep_destino}"
    session['endereco_envio_selecionado'] = endereco_via_cep
    pedido = Pedido.query.filter_by(usuario_id=current_user.id).filter(Pedido.status.in_(['ABERTO', 'PAGAMENTO'])).first()
    if pedido:
        pedido.endereco = endereco_via_cep
        db.session.commit()

    opcoes_frete = estimar_opcoes_frete(origem['uf'], destino['uf'], peso_gramas)
    opcoes_frete.append({"id": "excursao", "nome": "Envio por Excursão", "transportadora": "Excursão", "valor": VALOR_FRETE_EXCURSAO, "prazo": "A combinar"})
    return jsonify({"sucesso": True, "cep_origem": f"{cep_origem[:5]}-{cep_origem[5:]}", "endereco_destino": endereco_via_cep, "peso_gramas": peso_gramas, "opcoes": opcoes_frete})

@main_bp.route('/checkout-infinitepay', methods=['POST'])
@login_required
def checkout_pagamento():
    limpar_carrinhos_abandonados()
    pedido = pedido_atual_do_usuario(current_user.id)
    
    if not pedido or pedido.itens == '[]': 
        return jsonify({"sucesso": False, "mensagem": "Sua reserva expirou (30 minutos) e os itens voltaram ao estoque. Verifique sua sacola, pois algum produto pode ter esgotado."})

    endereco_selecionado = session.get('endereco_envio_selecionado')
    if endereco_selecionado:
        pedido.endereco = endereco_selecionado

    itens_reservados = json.loads(pedido.itens)
    subtotal_centavos = sum(round(float(i['preco']) * 100) * int(i['quantidade']) for i in itens_reservados)
    subtotal = subtotal_centavos / 100
    if subtotal < VALOR_MINIMO_ATACADO:
        return jsonify({"sucesso": False, "mensagem": f"Para finalizar a compra, o pedido mínimo é de R$ {VALOR_MINIMO_ATACADO:,.2f}. Adicione mais produtos ao carrinho."})

    dados = request.get_json(silent=True) or {}
    frete_tipo = str(dados.get('frete_tipo') or pedido.frete_tipo or '').strip()
    if frete_tipo not in {'Correios', 'Jadlog', 'Excursão', 'Retirada em Surubim'}:
        return jsonify({"sucesso": False, "mensagem": "Escolha uma forma de envio antes de finalizar o pedido."}), 400
    if frete_tipo == 'Excursão':
        frete = VALOR_FRETE_EXCURSAO
    elif frete_tipo == 'Retirada em Surubim':
        frete = 0
    else:
        try:
            frete = float(dados.get('frete', 0) or 0)
        except (TypeError, ValueError):
            frete = 0
        if not math.isfinite(frete) or frete <= 0:
            return jsonify({"sucesso": False, "mensagem": "Selecione novamente uma opção de frete válida."}), 400

    observacao = dados.get('observacao', pedido.observacao or '')
    if not isinstance(observacao, str) or len(observacao) > 2000:
        return jsonify({"sucesso": False, "mensagem": "A observação deve ter no máximo 2000 caracteres."}), 400

    if pedido.status == 'ABANDONADO':
        erro_estoque = reativar_pedido_abandonado(pedido, itens_reservados)
        if erro_estoque:
            return jsonify({"sucesso": False, "mensagem": erro_estoque}), 409

    total = subtotal
    total_pedido = subtotal + frete if frete_tipo == 'Excursão' else subtotal
    quantidade_total = sum(int(item['quantidade']) for item in itens_reservados)
    formatar_reais = lambda valor: f"R$ {valor:,.2f}".replace(',', '_').replace('.', ',').replace('_', '.')
    whatsapp = re.sub(r'\D', '', str(current_user.whatsapp or ''))
    if len(whatsapp) == 13 and whatsapp.startswith('55'):
        celular = f"+55 ({whatsapp[2:4]}) {whatsapp[4:9]}-{whatsapp[9:]}"
    elif len(whatsapp) == 11:
        celular = f"+55 ({whatsapp[:2]}) {whatsapp[2:7]}-{whatsapp[7:]}"
    elif len(whatsapp) == 10:
        celular = f"+55 ({whatsapp[:2]}) {whatsapp[2:6]}-{whatsapp[6:]}"
    else:
        celular = current_user.whatsapp or 'Não informado'

    endereco = 'Retirada em Surubim' if frete_tipo == 'Retirada em Surubim' else (pedido.endereco or 'Não informado')
    local_match = re.search(r' - (.+)/([A-Z]{2})(?: - CEP:|$)', endereco, re.IGNORECASE)
    local = f'{local_match.group(1).strip()}-{local_match.group(2).upper()}' if local_match else endereco
    origem = current_app.config.get('LOCAL_ORIGEM', 'MODA CENTER SANTA CRUZ')
    resumo = [
        f"Pedido #{pedido.id}",
        "",
        "--------------------",
        "Cliente:",
        f"Nome: {pedido.nome_cliente or current_user.nome}",
        f"WhatsApp: {celular}",
        f"Endereço de envio: {endereco}",
        f"Local: {local}",
        f"Observação do cliente: {observacao.strip() or 'Nenhuma'}",
        "Produtos:",
    ]
    for item in itens_reservados:
        produto = db.session.get(Produto, item.get('id'))
        referencia = produto.codigo if produto and produto.codigo else '-'
        quantidade = int(item['quantidade'])
        subtotal_item = float(item['preco']) * quantidade
        resumo.extend([
            f"# {item['nome']} - *{item['tamanho']}* ({item.get('cor') or 'Não informada'}) - Ref: {referencia}",
            f"Quantidade: {quantidade} / Valor: {formatar_reais(float(item['preco']))}",
            f"Subtotal: {formatar_reais(subtotal_item)}",
            "--------------------",
        ])
    resumo.extend([
        f"Quantidade Total: {quantidade_total}",
        f"Subtotal dos produtos: {formatar_reais(subtotal)}",
        f"{'Taxa de envio por excursão (somada ao pedido)' if frete_tipo == 'Excursão' else 'Frete estimado (não incluído no total)'}: {formatar_reais(frete)}",
        f"{'Total do pedido' if frete_tipo == 'Excursão' else 'Total da compra (produtos)'}: {formatar_reais(total_pedido)}",
        "--------------------",
        "--------------------",
        "Forma de Pagamento:",
        "PIX",
        "--------------------",
        "Forma de Envio:",
        frete_tipo,
        "--------------------",
        f"De: {origem} / Para: {local}",
        "Motorista ou Excursão:",
        "Nome: Não informado / Telefone: (00) 00000-0000",
        "Tipo de Veículo: Não informado",
        "Placa do Veículo: Não informado",
        "Horário da Excursão: Não informado",
        "--------------------",
        "Imprimir Pedido:",
        f"{request.url_root.rstrip('/')}/admin (localize o pedido #{pedido.id})",
    ])

    pedido.status = 'PAGO'
    pedido.frete_tipo = frete_tipo
    pedido.valor_total = total
    pedido.frete_estimado = frete
    pedido.observacao = observacao.strip() or None
    if frete_tipo == 'Retirada em Surubim':
        pedido.endereco = 'Retirada em Surubim'
    pedido.data_atualizacao = datetime.utcnow()
    db.session.commit()
    session.pop('endereco_envio_selecionado', None)

    numero_loja = re.sub(r'\D', '', str(current_app.config.get('WHATSAPP_LOJA', '558199475717')))
    url_whatsapp = f"https://wa.me/{numero_loja}?text={requests.utils.quote(chr(10).join(resumo))}"
    return jsonify({"sucesso": True, "url_whatsapp": url_whatsapp})

@main_bp.route('/api/mercadopago/webhook', methods=['POST', 'GET'])
def webhook_mercadopago():
    dados = request.get_json(silent=True) or {}
    payment_id = request.args.get('data.id') or request.args.get('id') or dados.get('data', {}).get('id')

    if payment_id:
        headers = {"Authorization": "Bearer APP_USR-4605924732795730-082514-374272a2de1d3b789462ba88224527e0-125327286"}
        res = requests.get(f"https://api.mercadopago.com/v1/payments/{payment_id}", headers=headers)
        if res.status_code == 200:
            payment_info = res.json()
            status_mp = payment_info.get("status")
            pedido_id = payment_info.get("external_reference")

            if status_mp == "approved" and pedido_id:
                pedido = Pedido.query.get(int(pedido_id))
                if pedido and pedido.status in ['ABERTO', 'PAGAMENTO']:
                    pedido.status = 'PAGO'
                    pedido.data_atualizacao = datetime.utcnow()
                    db.session.commit()

    return jsonify({"status": "received"}), 200