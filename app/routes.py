import os
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session, current_app, flash
from app.models import Produto, ProdutoImagem, Usuario, Pedido, Admin, Visita, ImagemSite, ImportacaoEstoque, ConfiguracaoLoja, EstoqueMovimento
from app import db
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import or_, text
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import IntegrityError
import requests
import json
import re
import math
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

main_bp = Blueprint('main', __name__)
VALOR_MINIMO_ATACADO = 330.00
VALOR_FRETE_EXCURSAO = 10.00
STATUS_PEDIDO_EDITAVEIS = {'ABERTO', 'PAGAMENTO', 'PAGO', 'SEPARACAO'}
STATUS_PEDIDOS_PAGOS = ('PAGO', 'SEPARACAO', 'ENVIADO', 'CONCLUIDO')
FUSO_RECIFE = ZoneInfo('America/Recife')
FUSO_UTC = timezone.utc


def recife_para_utc(data):
    return data.replace(tzinfo=FUSO_RECIFE).astimezone(FUSO_UTC).replace(tzinfo=None)


def utc_para_recife(data):
    if data.tzinfo is None:
        data = data.replace(tzinfo=FUSO_UTC)
    return data.astimezone(FUSO_RECIFE)


def data_local_recife(data):
    return utc_para_recife(data).date()

def limites_periodo_requisicao():
    if request.args.get('periodo') == 'tudo':
        return None, None, None
    inicio_raw = request.args.get('inicio', '').strip()
    fim_raw = request.args.get('fim', '').strip()
    if not inicio_raw and not fim_raw:
        return None, None, None
    if not inicio_raw or not fim_raw:
        return None, None, 'Informe a data inicial e final do período.'
    try:
        inicio_data = datetime.strptime(inicio_raw, '%Y-%m-%d').date()
        fim_data = datetime.strptime(fim_raw, '%Y-%m-%d').date()
    except ValueError:
        return None, None, 'Informe datas válidas para o período.'
    if inicio_data > fim_data:
        return None, None, 'A data inicial não pode ser posterior à data final.'
    inicio = recife_para_utc(datetime.combine(inicio_data, datetime.min.time()))
    fim_exclusivo = recife_para_utc(datetime.combine(fim_data + timedelta(days=1), datetime.min.time()))
    return inicio, fim_exclusivo, None


def data_dentro_periodo(data, inicio, fim_exclusivo):
    return bool(data and (inicio is None or data >= inicio) and (fim_exclusivo is None or data < fim_exclusivo))


def data_referencia_pedido(pedido):
    if pedido.status in STATUS_PEDIDOS_PAGOS:
        return pedido.data_pagamento or pedido.data_atualizacao
    return pedido.data_atualizacao


def garantir_numero_separacao(pedido):
    if pedido.numero_separacao is None:
        maior_numero = db.session.query(db.func.max(Pedido.numero_separacao)).scalar() or 0
        pedido.numero_separacao = int(maior_numero) + 1
    return pedido.numero_separacao

def compras_ativas():
    configuracao = db.session.get(ConfiguracaoLoja, 'compras_ativas')
    return configuracao.valor if configuracao else True

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


def imagem_hero_otimizada(caminho):
    base, _ = os.path.splitext(caminho)
    for variante in ('hero', 'gallery'):
        otimizada = f'{base}.{variante}.webp'
        if imagem_disponivel(otimizada):
            return otimizada
    return caminho


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
                    atualizar_estoque_variante(
                        prod,
                        item.get('cor'),
                        item['tamanho'],
                        item['quantidade'],
                        origem='PEDIDO',
                        motivo='Pedido abandonado',
                        pedido_id=p.id,
                        usuario_id=p.usuario_id,
                    )
        
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
    peso_total = 0
    for item in carrinho:
        try:
            quantidade = int(item.get('quantidade', 0))
        except (AttributeError, TypeError, ValueError) as erro:
            raise ValueError('A quantidade de um produto é inválida.') from erro
        if quantidade <= 0:
            raise ValueError('A quantidade de um produto é inválida.')
        produto_id = item.get('id')
        produto = db.session.get(Produto, produto_id) if produto_id is not None else None
        peso_unitario = produto.peso_gramas if produto and produto.peso_gramas else peso_por_produto
        peso_total += quantidade * peso_unitario
    return peso_total


def ler_medidas_produto(formulario):
    medidas = {}
    for campo, rotulo in (
        ('comprimento_cm', 'Comprimento'),
        ('largura_cm', 'Largura'),
        ('altura_cm', 'Altura'),
    ):
        valor = formulario.get(campo)
        if valor in (None, ''):
            medidas[campo] = None
            continue
        try:
            numero = float(valor)
        except (TypeError, ValueError) as erro:
            raise ValueError(f'{rotulo} deve ser informado em centímetros.') from erro
        if not math.isfinite(numero) or numero <= 0:
            raise ValueError(f'{rotulo} deve ser maior que zero.')
        medidas[campo] = numero

    dimensoes_preenchidas = sum(medidas[campo] is not None for campo in ('comprimento_cm', 'largura_cm', 'altura_cm'))
    if dimensoes_preenchidas not in (0, 3):
        raise ValueError('Preencha comprimento, largura e altura juntos ou deixe todas as dimensões vazias.')

    valor_peso = formulario.get('peso_gramas')
    if valor_peso in (None, ''):
        medidas['peso_gramas'] = None
    else:
        try:
            peso = int(valor_peso)
        except (TypeError, ValueError) as erro:
            raise ValueError('Peso deve ser informado em gramas inteiras.') from erro
        if peso <= 0:
            raise ValueError('Peso deve ser maior que zero.')
        medidas['peso_gramas'] = peso
    return medidas


def estimar_opcoes_frete(uf_origem, uf_destino, peso_gramas):
    regiao_origem = next((nome for nome, ufs in REGIOES_BRASIL.items() if uf_origem in ufs), None)
    regiao_destino = next((nome for nome, ufs in REGIOES_BRASIL.items() if uf_destino in ufs), None)
    base_pac = 15.0 if regiao_origem == regiao_destino else 28.0
    faixas_kg = max(1, math.ceil(peso_gramas / 1000))
    valor_pac = base_pac + (faixas_kg - 1) * 5.0
    return [
        {"id": 1, "nome": "PAC", "transportadora": "Correios", "valor": round(valor_pac, 2), "prazo": "6 a 8 dias úteis"},
        {"id": 2, "nome": "Sedex", "transportadora": "Correios", "valor": round(valor_pac + 22.50, 2), "prazo": "2 a 3 dias úteis"},
    ]

def registrar_movimento_estoque(produto, cor='GERAL', nome_tamanho='GERAL', delta=0, origem='PEDIDO', motivo=None, pedido_id=None, usuario_id=None):
    if produto is None or delta == 0:
        return None
    tipo = 'SAIDA' if delta < 0 else 'ENTRADA'
    movimento = EstoqueMovimento(
        produto_id=produto.id,
        pedido_id=pedido_id,
        usuario_id=usuario_id,
        cor=str(cor or 'GERAL')[:80],
        tamanho=str(nome_tamanho or 'GERAL')[:50],
        quantidade=abs(int(delta)),
        tipo=tipo,
        origem=str(origem or 'PEDIDO').upper(),
        motivo=(motivo or '').strip()[:200] or None,
        data_movimento=datetime.utcnow(),
    )
    db.session.add(movimento)
    return movimento


def atualizar_estoque_variante(produto, cor, nome_tamanho, delta, origem='PEDIDO', motivo=None, pedido_id=None, usuario_id=None):
    variantes = variantes_do_produto(produto)
    for variante in variantes:
        mesma_cor = chave_cor(variante.get('cor')) == chave_cor(cor)
        if mesma_cor:
            for tamanho in variante.get('tamanhos', []):
                if tamanho['nome'].casefold() == str(nome_tamanho).casefold():
                    estoque_anterior = int(tamanho.get('estoque', 0))
                    tamanho['estoque'] = max(0, estoque_anterior + delta)
                    produto.variantes = json.dumps(variantes, ensure_ascii=False)
                    registrar_movimento_estoque(produto, cor, nome_tamanho, delta, origem=origem, motivo=motivo, pedido_id=pedido_id, usuario_id=usuario_id)
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
        atualizar_estoque_variante(
            reserva['produto'],
            reserva['cor'],
            reserva['tamanho'],
            -reserva['quantidade'],
            origem='PEDIDO',
            motivo='Reativação do pedido abandonado',
            pedido_id=pedido.id,
            usuario_id=pedido.usuario_id,
        )
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
        imagem_hero_otimizada(imagens_site[chave])
        for chave in ('banner_hero', 'banner_hero_2', 'banner_hero_3')
        if imagem_disponivel(imagens_site.get(chave))
    ]

    categoria = request.args.get('categoria', '').strip().casefold()
    produtos = Produto.query.filter_by(ativo=True).order_by(Produto.promocao.desc(), Produto.nome.asc()).all()
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
                           pedido_sem_minimo=current_user.is_authenticated and current_user.pedido_sem_minimo,
                           compras_ativas=compras_ativas(),
                           google_login_enabled=current_app.config.get('GOOGLE_LOGIN_ENABLED', False),
                           categoria_atual=categoria)

@main_bp.route('/api/produtos/buscar')
def api_buscar_produtos():
    termo = re.sub(r'\s+', ' ', str(request.args.get('q') or '').strip())
    if len(termo) < 2:
        return jsonify([])

    produtos = Produto.query.filter(
        Produto.ativo.is_(True),
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

    if Admin.query.count() == 0 and current_app.config.get('ADMIN_EMAIL') and current_app.config.get('ADMIN_PASSWORD'):
        db.session.add(Admin(
            email=current_app.config['ADMIN_EMAIL'],
            senha=generate_password_hash(current_app.config['ADMIN_PASSWORD'], method='pbkdf2:sha256')
        ))
        db.session.commit()

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
    return render_template('admin.html', categorias_produto=CATEGORIAS_PRODUTO, compras_ativas=compras_ativas())

@main_bp.route('/api/admin/compras', methods=['POST'])
def api_admin_compras():
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado."}), 403

    ativo = (request.get_json(silent=True) or {}).get('ativas')
    if not isinstance(ativo, bool):
        return jsonify({"sucesso": False, "mensagem": "Informe se as compras devem ficar ativas."}), 400

    configuracao = db.session.get(ConfiguracaoLoja, 'compras_ativas')
    if configuracao is None:
        configuracao = ConfiguracaoLoja(chave='compras_ativas', valor=ativo)
        db.session.add(configuracao)
    else:
        configuracao.valor = ativo
    db.session.commit()
    return jsonify({"sucesso": True, "ativas": configuracao.valor})

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
    inicio, fim_exclusivo, erro_periodo = limites_periodo_requisicao()
    if erro_periodo:
        return jsonify({"sucesso": False, "mensagem": erro_periodo}), 400
    limpar_carrinhos_abandonados()
    
    pedidos = Pedido.query.options(joinedload(Pedido.usuario)).order_by(Pedido.id.asc()).all()
    numeros_pedidos_pagos = {
        pedido.id: numero
        for numero, pedido in enumerate(
            sorted(
                (pedido for pedido in pedidos if pedido.status in STATUS_PEDIDOS_PAGOS),
                key=lambda pedido: (data_referencia_pedido(pedido) or datetime.min, pedido.id),
            ),
            start=1,
        )
    }
    ids_produtos = {
        int(item['id'])
        for pedido in pedidos
        if pedido.itens and pedido.itens != '[]'
        for item in json.loads(pedido.itens)
        if isinstance(item.get('id'), (int, str)) and str(item['id']).isdigit()
    }
    produtos = Produto.query.options(selectinload(Produto.imagens)).filter(Produto.id.in_(ids_produtos)).all() if ids_produtos else []
    produtos_por_id = {produto.id: produto for produto in produtos}
    resultado = []
    for p in pedidos:
        itens_enriquecidos = []
        if p.itens and p.itens != '[]':
            for item in json.loads(p.itens):
                id_produto = item.get('id')
                prod = produtos_por_id.get(int(id_produto)) if str(id_produto).isdigit() else None
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
            "id": p.id, "numero_separacao": numeros_pedidos_pagos.get(p.id), "cliente": p.nome_cliente or (p.usuario.nome if p.usuario else 'Cliente não identificado'), "whatsapp": p.usuario.whatsapp if p.usuario else None, "whatsapp_url": link_whatsapp_cliente(p.usuario.whatsapp if p.usuario else None), "nome_cliente": p.nome_cliente or (p.usuario.nome if p.usuario else 'Cliente não identificado'), "observacao": p.observacao or '', "endereco": p.endereco, "frete_tipo": p.frete_tipo,
            "status": p.status, "forma_pagamento": p.forma_pagamento, "total": p.valor_total, "frete_estimado": p.frete_estimado or 0, "itens": itens_enriquecidos, "atualizado": utc_para_recife(p.data_atualizacao).strftime('%d/%m %H:%M'), "no_periodo": data_dentro_periodo(data_referencia_pedido(p), inicio, fim_exclusivo)
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
        if subtotal < VALOR_MINIMO_ATACADO and not pedido.usuario.pedido_sem_minimo:
            return jsonify({"sucesso": False, "mensagem": f"Não é possível confirmar o pedido abaixo do mínimo de R$ {VALOR_MINIMO_ATACADO:,.2f}."}), 409
    if status_novo == 'PAGO':
        return jsonify({"sucesso": False, "mensagem": "O status PAGO só é definido após a confirmação do pagamento pelo Mercado Pago."}), 409
    if status_novo in {'SEPARACAO', 'ENVIADO', 'CONCLUIDO'} and pedido.status not in {'PAGO', 'SEPARACAO', 'ENVIADO', 'CONCLUIDO'}:
        return jsonify({"sucesso": False, "mensagem": "Só é possível avançar o pedido após a confirmação do pagamento."}), 409
    status_anterior = pedido.status
    pedido.status = status_novo
    if status_novo == 'SEPARACAO' and status_anterior != 'SEPARACAO':
        maior_numero = db.session.query(db.func.max(Pedido.numero_separacao)).scalar() or 0
        pedido.numero_separacao = int(maior_numero) + 1
    elif status_novo in {'PAGO', 'SEPARACAO', 'ENVIADO', 'CONCLUIDO'}:
        garantir_numero_separacao(pedido)
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

    try:
        itens_antigos = json.loads(pedido.itens or '[]')
    except (TypeError, json.JSONDecodeError):
        return jsonify({"sucesso": False, "mensagem": "Os itens atuais do pedido estão inválidos."}), 409

    if 'itens' in dados:
        itens_solicitados = dados.get('itens')
        if not isinstance(itens_solicitados, list):
            return jsonify({"sucesso": False, "mensagem": "A lista de itens enviada é inválida."}), 400
    elif quantidades is not None:
        if not isinstance(quantidades, list) or len(quantidades) != len(itens_antigos):
            return jsonify({"sucesso": False, "mensagem": "A lista de quantidades não corresponde aos itens do pedido."}), 400
        itens_solicitados = [
            {**item, 'quantidade': quantidade}
            for item, quantidade in zip(itens_antigos, quantidades)
        ]
    else:
        itens_solicitados = [dict(item) for item in itens_antigos]

    itens_antigos_por_chave = {}
    for item_antigo in itens_antigos:
        try:
            produto_id_antigo = int(item_antigo['id'])
            quantidade_antiga = int(item_antigo.get('quantidade') or 0)
            cor_antiga = item_antigo.get('cor')
            tamanho_antigo = str(item_antigo.get('tamanho') or '').strip()
        except (KeyError, TypeError, ValueError):
            return jsonify({"sucesso": False, "mensagem": "Um item existente no pedido está inválido."}), 409
        if quantidade_antiga <= 0 or not tamanho_antigo:
            return jsonify({"sucesso": False, "mensagem": "Um item existente no pedido está inválido."}), 409
        chave_antiga = (produto_id_antigo, chave_cor(cor_antiga), tamanho_antigo.casefold())
        entrada_antiga = itens_antigos_por_chave.setdefault(chave_antiga, {
            'item': dict(item_antigo),
            'quantidade': 0,
            'cor': cor_antiga,
            'tamanho': tamanho_antigo,
        })
        entrada_antiga['quantidade'] += quantidade_antiga

    itens_solicitados_por_chave = {}
    for item_solicitado in itens_solicitados:
        if not isinstance(item_solicitado, dict):
            return jsonify({"sucesso": False, "mensagem": "Um item enviado para edição é inválido."}), 400
        produto_id = item_solicitado.get('id')
        quantidade = item_solicitado.get('quantidade')
        tamanho = str(item_solicitado.get('tamanho') or '').strip()
        cor = item_solicitado.get('cor')
        if isinstance(produto_id, bool) or not str(produto_id or '').isdigit():
            return jsonify({"sucesso": False, "mensagem": "Selecione um produto válido."}), 400
        if isinstance(quantidade, bool) or not (
            isinstance(quantidade, int)
            or isinstance(quantidade, str) and quantidade.strip().isdigit()
        ):
            return jsonify({"sucesso": False, "mensagem": "Informe quantidades inteiras válidas."}), 400
        quantidade = int(quantidade)
        if quantidade < 0:
            return jsonify({"sucesso": False, "mensagem": "As quantidades não podem ser negativas."}), 400
        if not tamanho or cor is not None and not isinstance(cor, str):
            return jsonify({"sucesso": False, "mensagem": "Selecione uma cor e um tamanho válidos."}), 400
        if quantidade == 0:
            continue
        produto_id = int(produto_id)
        chave = (produto_id, chave_cor(cor), tamanho.casefold())
        entrada = itens_solicitados_por_chave.setdefault(chave, {
            'cor': cor,
            'tamanho': tamanho,
            'quantidade': 0,
        })
        entrada['quantidade'] += quantidade

    if not itens_solicitados_por_chave:
        return jsonify({"sucesso": False, "mensagem": "Mantenha ao menos um item no pedido."}), 400

    itens_novos = []
    alteracoes_estoque = {}
    chaves_finais = set(itens_solicitados_por_chave)
    for chave, entrada in itens_solicitados_por_chave.items():
        produto_id, _, _ = chave
        quantidade_nova = entrada['quantidade']
        entrada_antiga = itens_antigos_por_chave.get(chave)
        quantidade_antiga = entrada_antiga['quantidade'] if entrada_antiga else 0
        delta = quantidade_nova - quantidade_antiga
        produto = db.session.get(Produto, produto_id)

        if delta == 0 and entrada_antiga:
            item_novo = dict(entrada_antiga['item'])
            item_novo['quantidade'] = quantidade_nova
            itens_novos.append(item_novo)
            continue
        if not produto:
            return jsonify({"sucesso": False, "mensagem": "Um dos produtos selecionados não está mais cadastrado."}), 409
        if delta > 0 and not produto.ativo:
            return jsonify({"sucesso": False, "mensagem": f"O produto '{produto.nome}' está inativo e não pode ser adicionado ao pedido."}), 409

        variante = next((
            variante for variante in variantes_do_produto(produto)
            if chave_cor(variante.get('cor')) == chave[1]
        ), None)
        tamanho_produto = next((
            tamanho for tamanho in (variante or {}).get('tamanhos', [])
            if str(tamanho.get('nome') or '').casefold() == chave[2]
        ), None)
        if not tamanho_produto:
            return jsonify({"sucesso": False, "mensagem": f"A variação {produto.nome} ({entrada['cor'] or 'Cor não definida'}, {entrada['tamanho']}) não está mais disponível no catálogo."}), 409

        alteracoes_estoque[chave] = {
            'produto': produto,
            'cor': variante.get('cor'),
            'tamanho': tamanho_produto['nome'],
            'delta': delta,
            'estoque': int(tamanho_produto.get('estoque') or 0),
        }
        if entrada_antiga:
            item_novo = dict(entrada_antiga['item'])
        else:
            item_novo = {
                'id': produto.id,
                'nome': produto.nome,
                'cor': variante.get('cor'),
                'tamanho': tamanho_produto['nome'],
                'preco': float(tamanho_produto.get('preco') or produto.preco),
                'imagem': produto.imagem_url,
                'codigo': produto.codigo,
            }
        item_novo['quantidade'] = quantidade_nova
        itens_novos.append(item_novo)

    for chave, entrada_antiga in itens_antigos_por_chave.items():
        if chave in chaves_finais:
            continue
        produto = db.session.get(Produto, chave[0])
        if not produto:
            return jsonify({"sucesso": False, "mensagem": f"O produto {entrada_antiga['item'].get('nome', '')} não está mais cadastrado e seu estoque não pode ser atualizado."}), 409
        variante = next((
            variante for variante in variantes_do_produto(produto)
            if chave_cor(variante.get('cor')) == chave[1]
        ), None)
        tamanho_produto = next((
            tamanho for tamanho in (variante or {}).get('tamanhos', [])
            if str(tamanho.get('nome') or '').casefold() == chave[2]
        ), None)
        if not tamanho_produto:
            return jsonify({"sucesso": False, "mensagem": f"A variação do produto {entrada_antiga['item'].get('nome', '')} não está mais disponível para devolução ao estoque."}), 409
        alteracoes_estoque[chave] = {
            'produto': produto,
            'cor': variante.get('cor'),
            'tamanho': tamanho_produto['nome'],
            'delta': -entrada_antiga['quantidade'],
            'estoque': int(tamanho_produto.get('estoque') or 0),
        }

    subtotal_novo = sum(float(item.get('preco') or 0) * int(item['quantidade']) for item in itens_novos)
    if pedido.status in {'PAGO', 'SEPARACAO'} and subtotal_novo < VALOR_MINIMO_ATACADO and not pedido.usuario.pedido_sem_minimo:
        return jsonify({"sucesso": False, "mensagem": f"O pedido confirmado não pode ficar abaixo do mínimo de R$ {VALOR_MINIMO_ATACADO:,.2f}."}), 409
    for alteracao in alteracoes_estoque.values():
        if alteracao['delta'] > alteracao['estoque']:
            return jsonify({"sucesso": False, "mensagem": f"Estoque insuficiente para {alteracao['produto'].nome} ({alteracao['cor'] or 'Cor não definida'}, {alteracao['tamanho']}). Disponível: {alteracao['estoque']}."}), 409

    try:
        for alteracao in alteracoes_estoque.values():
            atualizar_estoque_variante(
                alteracao['produto'],
                alteracao['cor'],
                alteracao['tamanho'],
                -alteracao['delta'],
            )
        subtotal_novo = sum(float(item.get('preco') or 0) * int(item.get('quantidade') or 0) for item in itens_novos)
        pedido.itens = json.dumps(itens_novos, ensure_ascii=False)
        pedido.valor_total = round(subtotal_novo, 2)
        pedido.frete_estimado = max(0, float(pedido.frete_estimado or 0))
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

@main_bp.route('/api/admin/pedidos/excluir', methods=['POST'])
def api_admin_excluir_pedido():
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado."}), 403
    dados = request.get_json(silent=True) or {}
    pedido = db.session.get(Pedido, dados.get('id'))
    if not pedido:
        return jsonify({"sucesso": False, "mensagem": "Pedido não encontrado."}), 404
    if pedido.status != 'CONCLUIDO':
        return jsonify({"sucesso": False, "mensagem": "Somente pedidos concluídos podem ser excluídos."}), 409

    try:
        db.session.delete(pedido)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Falha ao excluir pedido concluído %s.', pedido.id)
        return jsonify({"sucesso": False, "mensagem": "Não foi possível excluir o pedido."}), 500

    return jsonify({"sucesso": True, "mensagem": "Pedido concluído excluído."})

@main_bp.route('/api/admin/produtos', methods=['GET'])
def api_admin_produtos():
    if not session.get('admin_logado'): return jsonify([])
    produtos = Produto.query.options(selectinload(Produto.imagens)).all()
    return jsonify([{
        "id": p.id, "codigo": p.codigo, "nome": p.nome, "categoria": categoria_para_exibicao(p), "categoria_manual": bool(p.categoria), "preco": p.preco,
        "precos": {tamanho: preco_tamanho(p, tamanho) for tamanho in ('P', 'M', 'G', 'GG')}, "grade": grade_do_produto(p), "cores": p.cores_config, "variantes": variantes_com_cor_hex(variantes_do_produto(p)), "imagem_url": p.imagem_url,
        "imagens": [{"id": imagem.id, "url": imagem.imagem_url} for imagem in p.imagens],
        "promocao": p.promocao, "ativo": p.ativo,
        "comprimento_cm": p.comprimento_cm, "largura_cm": p.largura_cm,
        "altura_cm": p.altura_cm, "peso_gramas": p.peso_gramas,
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

@main_bp.route('/api/admin/produtos/<int:produto_id>/ativo', methods=['POST'])
def api_admin_definir_ativo_produto(produto_id):
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado."}), 403
    produto = db.session.get(Produto, produto_id)
    if not produto:
        return jsonify({"sucesso": False, "mensagem": "Produto não encontrado."}), 404
    ativo = (request.get_json(silent=True) or {}).get('ativo')
    if not isinstance(ativo, bool):
        return jsonify({"sucesso": False, "mensagem": "Estado do produto inválido."}), 400
    produto.ativo = ativo
    db.session.commit()
    return jsonify({"sucesso": True, "ativo": produto.ativo})

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
    dados = request.get_json() or {}
    prod = Produto.query.get(dados.get('id'))
    if not prod:
        return jsonify({"sucesso": False})

    tamanhos = ('p', 'm', 'g', 'gg')
    for tamanho in tamanhos:
        valor_atual = getattr(prod, f'estoque_{tamanho}', 0) or 0
        valor_novo = int(dados.get(tamanho) or 0)
        if valor_novo != valor_atual:
            delta = valor_novo - valor_atual
            setattr(prod, f'estoque_{tamanho}', valor_novo)
            registrar_movimento_estoque(
                prod,
                cor='GERAL',
                nome_tamanho=tamanho.upper(),
                delta=delta,
                origem='AJUSTE_ADMIN',
                motivo='Ajuste manual do administrador',
                usuario_id=current_user.id if current_user.is_authenticated else None,
            )
    db.session.commit()
    return jsonify({"sucesso": True})

@main_bp.route('/api/admin/estoque/historico')
def api_admin_estoque_historico():
    if not session.get('admin_logado'):
        return jsonify([])
    movimentos = EstoqueMovimento.query.order_by(EstoqueMovimento.data_movimento.desc(), EstoqueMovimento.id.desc()).limit(200).all()
    return jsonify([
        {
            'id': movimento.id,
            'produto_id': movimento.produto_id,
            'produto': movimento.produto.nome if movimento.produto else 'Produto removido',
            'cor': movimento.cor,
            'tamanho': movimento.tamanho,
            'quantidade': movimento.quantidade,
            'tipo': movimento.tipo,
            'origem': movimento.origem,
            'motivo': movimento.motivo or '',
            'data_movimento': movimento.data_movimento.strftime('%d/%m/%Y %H:%M:%S') if movimento.data_movimento else '',
        }
        for movimento in movimentos
    ])

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
        medidas = ler_medidas_produto(request.form)
        novo_produto = Produto(codigo=codigo, nome=nome, categoria=categoria, preco=preco_base, preco_p=precos['p'], preco_m=precos['m'], preco_g=precos['g'], preco_gg=precos['gg'], grade=json.dumps(grade_normalizada, ensure_ascii=False), cores=json.dumps(cores_normalizadas), variantes=json.dumps(variantes_normalizadas, ensure_ascii=False), etiqueta='NOVO', imagem_url='img/default.jpg', estoque_p=quantidades[0], estoque_m=quantidades[1], estoque_g=quantidades[2], estoque_gg=quantidades[3], **medidas)
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

        medidas = ler_medidas_produto(request.form)
        for campo, valor in medidas.items():
            if campo in request.form:
                setattr(prod, campo, valor)

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

        if request.form.get('aplicar_medidas_a_todos') == 'true':
            for produto in Produto.query.all():
                for campo in medidas:
                    setattr(produto, campo, getattr(prod, campo))

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
    inicio, fim_exclusivo, erro_periodo = limites_periodo_requisicao()
    if erro_periodo:
        return jsonify({"sucesso": False, "mensagem": erro_periodo}), 400
    limpar_carrinhos_abandonados()
    
    pedidos = Pedido.query.all()
    fat = 0; qtd_vendas = 0; pecas = 0; abandonos = 0; abertos = 0; abertos_periodo = 0; fretes = {}; valor_perdido = 0
    produtos_vendidos = {}
    clientes_compras = {}

    for p in pedidos:
        no_periodo = data_dentro_periodo(data_referencia_pedido(p), inicio, fim_exclusivo)
        if p.status in ['ABERTO', 'PAGAMENTO']:
            abertos += 1
            if no_periodo:
                abertos_periodo += 1
        if not no_periodo:
            continue
        if p.status in STATUS_PEDIDOS_PAGOS:
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
            
    total_iniciados = abandonos + abertos_periodo + qtd_vendas
    taxa_abandono = (abandonos / total_iniciados * 100) if total_iniciados > 0 else 0
    ticket_medio = (fat / qtd_vendas) if qtd_vendas > 0 else 0
    top_produtos = sorted(produtos_vendidos.items(), key=lambda x: x[1], reverse=True)[:5]
    top_clientes = sorted(clientes_compras.items(), key=lambda x: x[1], reverse=True)[:5]
    
    prod_risco = Produto.query.filter(or_(Produto.estoque_p <= 5, Produto.estoque_m <= 5, Produto.estoque_g <= 5, Produto.estoque_gg <= 5)).all()
    risco_ruptura = [{"nome": pr.nome, "estoque": f"P:{pr.estoque_p} M:{pr.estoque_m} G:{pr.estoque_g} GG:{pr.estoque_gg}"} for pr in prod_risco]

    return jsonify({
        "kpis": {"faturamento": fat, "ticket_medio": ticket_medio, "pecas_vendidas": pecas, "taxa_abandono": taxa_abandono, "valor_perdido": valor_perdido},
        "graficos": {"produtos_labels": [x[0][:15]+"..." for x in top_produtos], "produtos_data": [x[1] for x in top_produtos], "clientes_labels": [x[0][:18]+"..." for x in top_clientes], "clientes_data": [x[1] for x in top_clientes], "fretes_labels": list(fretes.keys()), "fretes_data": list(fretes.values())},
        "periodo": {"inicio": inicio.date().isoformat() if inicio else None, "fim": (fim_exclusivo - timedelta(days=1)).date().isoformat() if fim_exclusivo else None},
        "atuais": {"pedidos_abertos": abertos},
        "risco_ruptura": risco_ruptura
    })

@main_bp.route('/api/admin/relatorios')
def api_admin_relatorios():
    if not session.get('admin_logado'): return jsonify({})
    inicio, fim_exclusivo, erro_periodo = limites_periodo_requisicao()
    if erro_periodo:
        return jsonify({"sucesso": False, "mensagem": erro_periodo}), 400
    hoje = datetime.now(FUSO_RECIFE).date()
    if request.args.get('periodo') == 'tudo':
        datas_iniciais = [
            data.date() for data in (
                db.session.query(db.func.min(Visita.data_visita)).scalar(),
                db.session.query(db.func.min(db.func.coalesce(Pedido.data_pagamento, Pedido.data_atualizacao))).scalar(),
            ) if data
        ]
        inicio_data = min((data_local_recife(data) for data in datas_iniciais), default=hoje)
        fim_data = hoje
    elif inicio and fim_exclusivo:
        inicio_data = inicio.date()
        fim_data = (fim_exclusivo - timedelta(days=1)).date()
    else:
        inicio_data = hoje - timedelta(days=6)
        fim_data = hoje

    quantidade_dias = (fim_data - inicio_data).days + 1
    agrupar_por_mes = quantidade_dias > 90
    if agrupar_por_mes:
        cursor = inicio_data.replace(day=1)
        datas_periodo = []
        while cursor <= fim_data:
            datas_periodo.append(cursor)
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        datas_labels = [data.strftime('%m/%Y') for data in datas_periodo]
        chaves_indices = {data.strftime('%Y-%m'): indice for indice, data in enumerate(datas_periodo)}
    else:
        datas_periodo = [inicio_data + timedelta(days=indice) for indice in range(quantidade_dias)]
        datas_labels = [data.strftime('%d/%m') for data in datas_periodo]
        chaves_indices = {data.isoformat(): indice for indice, data in enumerate(datas_periodo)}

    acessos_data = [0] * len(datas_labels)
    vendas_data = [0] * len(datas_labels)
    data_inicio_filtro = recife_para_utc(datetime.combine(inicio_data, datetime.min.time()))
    data_fim_filtro = recife_para_utc(datetime.combine(fim_data + timedelta(days=1), datetime.min.time()))
    visitas = Visita.query.filter(
        Visita.data_visita >= data_inicio_filtro,
        Visita.data_visita < data_fim_filtro,
    ).all()
    pedidos = Pedido.query.filter(
        Pedido.status.in_(STATUS_PEDIDOS_PAGOS),
        db.func.coalesce(Pedido.data_pagamento, Pedido.data_atualizacao) >= data_inicio_filtro,
        db.func.coalesce(Pedido.data_pagamento, Pedido.data_atualizacao) < data_fim_filtro,
    ).all()
    for visita in visitas:
        data_local = data_local_recife(visita.data_visita)
        chave = data_local.strftime('%Y-%m') if agrupar_por_mes else data_local.isoformat()
        if chave in chaves_indices:
            acessos_data[chaves_indices[chave]] += 1
    for pedido in pedidos:
        data_local = data_local_recife(data_referencia_pedido(pedido))
        chave = data_local.strftime('%Y-%m') if agrupar_por_mes else data_local.isoformat()
        if chave in chaves_indices:
            vendas_data[chaves_indices[chave]] += 1

    return jsonify({"labels": datas_labels, "acessos": acessos_data, "vendas": vendas_data, "agrupar_por_mes": agrupar_por_mes})

@main_bp.route('/api/admin/marketing')
def api_admin_marketing():
    if not session.get('admin_logado'): return jsonify({})
    inicio, fim_exclusivo, erro_periodo = limites_periodo_requisicao()
    if erro_periodo:
        return jsonify({"sucesso": False, "mensagem": erro_periodo}), 400
    if inicio is None and fim_exclusivo is None and request.args.get('periodo') != 'tudo':
        fim_exclusivo = datetime.utcnow()
        inicio = fim_exclusivo - timedelta(days=30)

    filtros_visitas = []
    filtros_pedidos = []
    filtros_pedidos_pagos = [Pedido.status.in_(STATUS_PEDIDOS_PAGOS)]
    if inicio:
        filtros_visitas.append(Visita.data_visita >= inicio)
        filtros_pedidos.append(Pedido.data_atualizacao >= inicio)
        filtros_pedidos_pagos.append(db.func.coalesce(Pedido.data_pagamento, Pedido.data_atualizacao) >= inicio)
    if fim_exclusivo:
        filtros_visitas.append(Visita.data_visita < fim_exclusivo)
        filtros_pedidos.append(Pedido.data_atualizacao < fim_exclusivo)
        filtros_pedidos_pagos.append(db.func.coalesce(Pedido.data_pagamento, Pedido.data_atualizacao) < fim_exclusivo)

    visitas = Visita.query.filter(*filtros_visitas).count()
    pedidos_iniciados = Pedido.query.filter(*filtros_pedidos).count()
    pedidos_pagos = Pedido.query.filter(*filtros_pedidos_pagos).count()
    taxa_conversao = (pedidos_pagos / visitas * 100) if visitas > 0 else 0
    
    filtros_abandonados = [Pedido.status == 'ABANDONADO']
    if inicio:
        filtros_abandonados.append(Pedido.data_atualizacao >= inicio)
    if fim_exclusivo:
        filtros_abandonados.append(Pedido.data_atualizacao < fim_exclusivo)
    abandonados_db = Pedido.query.filter(*filtros_abandonados).all()
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
        "pedido_sem_minimo": u.pedido_sem_minimo,
        "pedidos": sum(1 for pedido in u.pedidos if pedido.status in STATUS_PEDIDOS_PAGOS)
    } for u in usuarios])

@main_bp.route('/api/admin/usuarios', methods=['POST'])
def api_admin_criar_usuario():
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado"}), 403
    dados = request.get_json(silent=True) or {}
    nome = re.sub(r'\s+', ' ', str(dados.get('nome') or '').strip())
    whatsapp_normalizado = re.sub(r'\D', '', str(dados.get('whatsapp') or ''))
    if not nome or not whatsapp_normalizado:
        return jsonify({"sucesso": False, "mensagem": "Informe o nome e o WhatsApp do usuário."}), 400
    if len(nome) > 100:
        return jsonify({"sucesso": False, "mensagem": "O nome deve ter no máximo 100 caracteres."}), 400
    if len(whatsapp_normalizado) < 10 or len(whatsapp_normalizado) > 15:
        return jsonify({"sucesso": False, "mensagem": "Informe um número de WhatsApp válido."}), 400
    if any(re.sub(r'\D', '', usuario.whatsapp or '') == whatsapp_normalizado for usuario in Usuario.query.all()):
        return jsonify({"sucesso": False, "mensagem": "Este WhatsApp já está cadastrado."}), 409

    usuario = Usuario(
        nome=nome,
        email=f'whatsapp+{whatsapp_normalizado}@clientes.leyly.local',
        senha=generate_password_hash(secrets.token_urlsafe(32), method='pbkdf2:sha256'),
        whatsapp=whatsapp_normalizado,
        pedido_sem_minimo=bool(dados.get('pedido_sem_minimo')),
        cliente_especial=bool(dados.get('especial')),
    )
    db.session.add(usuario)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": "Não foi possível cadastrar: este WhatsApp já está associado a uma conta."}), 409
    return jsonify({"sucesso": True, "id": usuario.id})

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

@main_bp.route('/api/admin/usuarios/<int:usuario_id>/pedido-sem-minimo', methods=['POST'])
def api_admin_marcar_usuario_sem_minimo(usuario_id):
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado"}), 403
    usuario = db.session.get(Usuario, usuario_id)
    if not usuario:
        return jsonify({"sucesso": False, "mensagem": "Usuário não encontrado"}), 404
    dados = request.get_json(silent=True) or {}
    usuario.pedido_sem_minimo = bool(dados.get('pedido_sem_minimo'))
    db.session.commit()
    return jsonify({"sucesso": True, "pedido_sem_minimo": usuario.pedido_sem_minimo})

def _json_resposta(resposta):
    try:
        return resposta.json() or {}
    except ValueError:
        return {}


def _mensagem_erro_superfrete(dados, status_code):
    if isinstance(dados, dict):
        mensagem = dados.get('message') or dados.get('error')
        if mensagem:
            return str(mensagem)
    return f'A SuperFrete recusou a solicitação (HTTP {status_code}).'


def _url_impressao_superfrete(dados):
    if not isinstance(dados, dict):
        return None
    candidatos = [dados, dados.get('data'), dados.get('purchase')]
    for candidato in candidatos:
        if not isinstance(candidato, dict):
            continue
        impressao = candidato.get('print')
        if isinstance(impressao, dict) and impressao.get('url'):
            return impressao['url']
        if candidato.get('url'):
            return candidato['url']
        pedidos = candidato.get('orders')
        if isinstance(pedidos, list):
            for pedido in pedidos:
                if isinstance(pedido, dict):
                    impressao = pedido.get('print')
                    if isinstance(impressao, dict) and impressao.get('url'):
                        return impressao['url']
    return None


def _finalizar_etiqueta_superfrete(pedido, base_url, headers):
    try:
        resposta_checkout = requests.post(
            f'{base_url}/api/v0/checkout',
            json={'orders': [pedido.superfrete_order_id]},
            headers=headers,
            timeout=20,
        )
    except requests.RequestException:
        return jsonify({"sucesso": False, "mensagem": "O envio foi criado, mas não foi possível concluir o pagamento da etiqueta. Tente novamente."}), 502
    dados_checkout = _json_resposta(resposta_checkout)
    if not resposta_checkout.ok or (isinstance(dados_checkout, dict) and dados_checkout.get('success') is False):
        mensagem = _mensagem_erro_superfrete(dados_checkout, resposta_checkout.status_code)
        if resposta_checkout.ok:
            mensagem = 'Não foi possível concluir o pagamento da etiqueta na SuperFrete.'
        return jsonify({"sucesso": False, "mensagem": mensagem}), 502

    compra = dados_checkout.get('purchase', {}) if isinstance(dados_checkout, dict) else {}
    pedidos_comprados = compra.get('orders', []) if isinstance(compra, dict) else []
    dados_etiqueta = next((item for item in pedidos_comprados if str(item.get('id')) == pedido.superfrete_order_id), None) if isinstance(pedidos_comprados, list) else None
    if not dados_etiqueta and isinstance(pedidos_comprados, list) and pedidos_comprados:
        dados_etiqueta = pedidos_comprados[0]
    if isinstance(dados_etiqueta, dict):
        pedido.superfrete_tracking = dados_etiqueta.get('tracking') or pedido.superfrete_tracking
    url_etiqueta = _url_impressao_superfrete(dados_checkout)
    if not url_etiqueta:
        try:
            resposta_impressao = requests.post(
                f'{base_url}/api/v0/tag/print',
                json={'orders': [pedido.superfrete_order_id]},
                headers=headers,
                timeout=15,
            )
            dados_impressao = _json_resposta(resposta_impressao)
            if resposta_impressao.ok:
                url_etiqueta = _url_impressao_superfrete(dados_impressao)
        except requests.RequestException:
            url_etiqueta = None
    if not url_etiqueta or not str(url_etiqueta).startswith('https://'):
        db.session.commit()
        return jsonify({"sucesso": False, "mensagem": "A etiqueta foi paga, mas a SuperFrete não retornou um link PDF válido. Tente reimprimir."}), 502
    db.session.commit()
    return jsonify({"sucesso": True, "url_etiqueta": url_etiqueta, "reimpressao": False})


@main_bp.route('/api/admin/gerar-etiqueta/<int:pedido_id>', methods=['POST'])
def api_gerar_etiqueta(pedido_id):
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado."}), 403
    pedido = Pedido.query.get(pedido_id)
    if not pedido:
        return jsonify({"sucesso": False, "mensagem": "Pedido não encontrado."}), 404
    if pedido.status not in {'PAGO', 'SEPARACAO', 'ENVIADO', 'CONCLUIDO'}:
        return jsonify({"sucesso": False, "mensagem": "Etiqueta disponível apenas para pedidos confirmados."}), 409

    token = (
        current_app.config.get('SUPERFRETE_TOKEN')
        or os.environ.get('SUPERFRETE_TOKEN')
        or os.environ.get('SUPERFRETE_API_TOKEN')
        or ''
    ).strip()
    if not token:
        return jsonify({"sucesso": False, "mensagem": "SuperFrete não configurada. Defina SUPERFRETE_TOKEN no Render."}), 503

    base_url = str(current_app.config.get('SUPERFRETE_BASE_URL') or 'https://api.superfrete.com').rstrip('/')
    email_contato = current_app.config.get('SUPERFRETE_EMAIL') or current_app.config.get('ADMIN_EMAIL') or ''
    user_agent = f"LeylyModaFitness/1.0 ({email_contato})" if email_contato else 'LeylyModaFitness/1.0'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'User-Agent': user_agent,
    }

    if pedido.superfrete_order_id:
        try:
            resposta_info = requests.get(
                f'{base_url}/api/v0/order/info/{pedido.superfrete_order_id}',
                headers=headers,
                timeout=15,
            )
        except requests.RequestException:
            return jsonify({"sucesso": False, "mensagem": "Não foi possível consultar a etiqueta na SuperFrete."}), 502
        dados_info = _json_resposta(resposta_info)
        if not resposta_info.ok:
            return jsonify({"sucesso": False, "mensagem": _mensagem_erro_superfrete(dados_info, resposta_info.status_code)}), 502
        detalhes = dados_info.get('data', dados_info) if isinstance(dados_info, dict) else {}
        if not isinstance(detalhes, dict):
            detalhes = {}
        status_superfrete = str(detalhes.get('status') or '').casefold()
        if status_superfrete != 'pending':
            try:
                resposta_impressao = requests.post(
                    f'{base_url}/api/v0/tag/print',
                    json={'orders': [pedido.superfrete_order_id]},
                    headers=headers,
                    timeout=15,
                )
            except requests.RequestException:
                return jsonify({"sucesso": False, "mensagem": "A etiqueta existe, mas não foi possível gerar o link de impressão."}), 502
            dados_impressao = _json_resposta(resposta_impressao)
            url_etiqueta = _url_impressao_superfrete(dados_impressao)
            if not resposta_impressao.ok or not url_etiqueta:
                return jsonify({"sucesso": False, "mensagem": _mensagem_erro_superfrete(dados_impressao, resposta_impressao.status_code)}), 502
            return jsonify({"sucesso": True, "url_etiqueta": url_etiqueta, "reimpressao": True})
        return _finalizar_etiqueta_superfrete(pedido, base_url, headers)

    try:
        correspondencia_cep = re.search(
            r'(?<!\d)(?:\d{2}[\s.-]*\d{3}|\d{5})[\s.-]*\d{3}(?!\d)',
            str(pedido.endereco or ''),
        )
        cep_destino = re.sub(r'\D', '', correspondencia_cep.group(0)) if correspondencia_cep else ''
        if len(cep_destino) != 8:
            return jsonify({"sucesso": False, "mensagem": "O endereço do pedido precisa ter um CEP válido antes de emitir a etiqueta."}), 400
        resposta_cep = requests.get(f'https://viacep.com.br/ws/{cep_destino}/json/', timeout=10)
        destino = _json_resposta(resposta_cep)
        if not resposta_cep.ok or destino.get('erro') or not destino.get('logradouro') or not destino.get('localidade') or not destino.get('uf'):
            return jsonify({"sucesso": False, "mensagem": "Não foi possível validar o endereço de entrega pelo CEP."}), 400

        resposta_enderecos = requests.get(
            f'{base_url}/api/v0/user/addresses',
            headers=headers,
            timeout=15,
        )
        dados_enderecos = _json_resposta(resposta_enderecos)
        if not resposta_enderecos.ok:
            return jsonify({"sucesso": False, "mensagem": _mensagem_erro_superfrete(dados_enderecos, resposta_enderecos.status_code)}), 502
        enderecos = dados_enderecos.get('data', dados_enderecos) if isinstance(dados_enderecos, dict) else dados_enderecos
        if not isinstance(enderecos, list) or not enderecos:
            return jsonify({"sucesso": False, "mensagem": "Cadastre um endereço de remetente na conta SuperFrete antes de emitir etiquetas."}), 409
        remetente = next((endereco for endereco in enderecos if endereco.get('is_primary')), enderecos[0])
        remetente = {
            'name': remetente.get('name') or current_app.config.get('SUPERFRETE_SENDER_NAME') or '',
            'postal_code': re.sub(r'\D', '', str(remetente.get('postal_code') or '')),
            'address': remetente.get('address') or '',
            'number': str(remetente.get('number') or ''),
            'complement': remetente.get('complement') or None,
            'district': remetente.get('district') or 'NA',
            'city': remetente.get('city') or '',
            'state_abbr': str(remetente.get('state_abbr') or '').upper(),
        }
        if not all(remetente[campo] for campo in ('name', 'postal_code', 'address', 'city', 'state_abbr')):
            return jsonify({"sucesso": False, "mensagem": "Complete o endereço principal de remetente na conta SuperFrete."}), 409

        tipo_frete = str(pedido.frete_tipo or '').casefold()
        if 'jadlog' in tipo_frete:
            servicos_permitidos = {'3'}
        elif 'sedex' in tipo_frete:
            servicos_permitidos = {'2'}
        elif 'pac' in tipo_frete:
            servicos_permitidos = {'1'}
        elif 'correios' in tipo_frete:
            servicos_permitidos = {'1', '2'}
        else:
            return jsonify({"sucesso": False, "mensagem": "Este pedido não usa Correios ou Jadlog e não pode gerar etiqueta SuperFrete."}), 409

        itens = json.loads(pedido.itens or '[]')
        peso_gramas = peso_total_carrinho(itens, current_app.config['PESO_PRODUTO_GRAMAS'])
        pacote = {
            'height': current_app.config['SUPERFRETE_PACKAGE_HEIGHT_CM'],
            'width': current_app.config['SUPERFRETE_PACKAGE_WIDTH_CM'],
            'length': current_app.config['SUPERFRETE_PACKAGE_LENGTH_CM'],
            'weight': max(0.1, peso_gramas / 1000),
        }
        subtotal = sum(float(item.get('preco') or 0) * int(item.get('quantidade') or 0) for item in itens)
        resposta_cotacao = requests.post(
            f'{base_url}/api/v0/calculator',
            json={
                'from': {'postal_code': remetente['postal_code']},
                'to': {'postal_code': cep_destino},
                'package': pacote,
                'services': ','.join(sorted(servicos_permitidos)),
                'options': {'own_hand': False, 'receipt': False, 'insurance_value': round(subtotal, 2)},
            },
            headers=headers,
            timeout=20,
        )
        dados_cotacao = _json_resposta(resposta_cotacao)
        if not resposta_cotacao.ok:
            return jsonify({"sucesso": False, "mensagem": _mensagem_erro_superfrete(dados_cotacao, resposta_cotacao.status_code)}), 502
        cotacoes = dados_cotacao.get('data', dados_cotacao) if isinstance(dados_cotacao, dict) else dados_cotacao
        if not isinstance(cotacoes, list):
            cotacoes = []
        servicos = [
            servico for servico in cotacoes
            if isinstance(servico, dict)
            and str(servico.get('id')) in servicos_permitidos
            and not servico.get('has_error', servico.get('hasError', False))
        ]
        servico = min(servicos, key=lambda item: float(item.get('price') or 0), default=None)
        if not servico or float(servico.get('price') or 0) <= 0:
            return jsonify({"sucesso": False, "mensagem": "Não há serviço SuperFrete disponível para o CEP e forma de envio deste pedido."}), 409

        endereco_numero = re.search(r',\s*(?:n(?:úmero|umero|[º°o])?\.?\s*)?(\d{1,10})(?=\s*(?:,| - |$))', pedido.endereco or '', re.IGNORECASE)
        nome_destinatario = (pedido.nome_cliente or (pedido.usuario.nome if pedido.usuario else ''))[:50]
        destinatario = {
            'name': nome_destinatario,
            'phone': re.sub(r'\D', '', str(pedido.usuario.whatsapp or '')) if pedido.usuario else '',
            'address': destino['logradouro'][:50],
            'number': endereco_numero.group(1) if endereco_numero else '',
            'district': (destino.get('bairro') or 'NA')[:50],
            'city': destino['localidade'][:50],
            'state_abbr': str(destino['uf']).upper(),
            'postal_code': cep_destino,
        }
        email_destinatario = pedido.usuario.email if pedido.usuario else ''
        if email_destinatario and not email_destinatario.casefold().endswith('@clientes.leyly.local'):
            destinatario['email'] = email_destinatario
        produtos_declarados = [
            {
                'name': str(item.get('nome') or 'Produto')[:100],
                'quantity': int(item.get('quantidade') or 0),
                'unitary_value': round(float(item.get('preco') or 0), 2),
            }
            for item in itens if int(item.get('quantidade') or 0) > 0
        ]
        resposta_carrinho = requests.post(
            f'{base_url}/api/v0/cart',
            json={
                'from': remetente,
                'to': destinatario,
                'service': int(servico['id']),
                'volumes': [pacote],
                'products': produtos_declarados,
                'options': {'insurance_value': round(subtotal, 2), 'non_commercial': True},
                'platform': 'Leyly/1.0',
            },
            headers=headers,
            timeout=20,
        )
        dados_carrinho = _json_resposta(resposta_carrinho)
        if not resposta_carrinho.ok:
            return jsonify({"sucesso": False, "mensagem": _mensagem_erro_superfrete(dados_carrinho, resposta_carrinho.status_code)}), 502
        carrinho = dados_carrinho.get('data', dados_carrinho) if isinstance(dados_carrinho, dict) else {}
        pedido.superfrete_order_id = str(carrinho.get('id') or '') if isinstance(carrinho, dict) else ''
        if not pedido.superfrete_order_id:
            return jsonify({"sucesso": False, "mensagem": "A SuperFrete não retornou o identificador do envio."}), 502
        db.session.commit()
    except (requests.RequestException, TypeError, ValueError, KeyError) as erro:
        db.session.rollback()
        current_app.logger.exception('Falha ao preparar etiqueta SuperFrete do pedido %s.', pedido_id)
        return jsonify({"sucesso": False, "mensagem": f"Não foi possível preparar a etiqueta: {erro}"}), 502

    return _finalizar_etiqueta_superfrete(pedido, base_url, headers)

# ==========================================
# CHECKOUT E VALIDAÇÃO DE ESTOQUE
# ==========================================
@main_bp.route('/api/carrinho/sync', methods=['POST'])
@login_required
def sync_carrinho():
    if not compras_ativas():
        return jsonify({"sucesso": False, "mensagem": "As compras estão temporariamente pausadas. Tente novamente mais tarde."}), 409
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
                atualizar_estoque_variante(
                    prod,
                    item.get('cor'),
                    item['tamanho'],
                    item['quantidade'],
                    origem='PEDIDO',
                    motivo='Atualização de pedido em aberto',
                    pedido_id=pedido.id,
                    usuario_id=current_user.id,
                )
    
    if novo_carrinho:
        for item in novo_carrinho:
            prod = db.session.get(Produto, item.get('id'))
            if not prod:
                db.session.rollback()
                return jsonify({"sucesso": False, "mensagem": f"O produto '{item.get('nome', 'selecionado')}' foi removido do catálogo."}), 409
            if not prod.ativo:
                db.session.rollback()
                return jsonify({"sucesso": False, "mensagem": f"O produto '{prod.nome}' está inativo e não pode ser comprado."}), 409

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
                item_indisponivel = {
                    'id': prod.id,
                    'nome': prod.nome,
                    'cor': item.get('cor'),
                    'tamanho': item['tamanho'],
                }
                db.session.rollback()
                return jsonify({
                    "sucesso": False, 
                    "mensagem": f"O item '{prod.nome}' (Tam: {item['tamanho'].upper()}) esgotou ou não possui a quantidade desejada. Restam {estoque_disp} unidades no momento.",
                    "item_indisponivel": item_indisponivel,
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
            atualizar_estoque_variante(
                prod,
                item.get('cor'),
                item['tamanho'],
                -quantidade,
                origem='PEDIDO',
                motivo='Pedido em aberto',
                pedido_id=pedido.id,
                usuario_id=current_user.id,
            )

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

@main_bp.route('/checkout-mercadopago', methods=['POST'])
@main_bp.route('/checkout-infinitepay', methods=['POST'])
@login_required
def checkout_pagamento():
    if not compras_ativas():
        return jsonify({"sucesso": False, "mensagem": "As compras estão temporariamente pausadas. Tente novamente mais tarde."}), 409
    limpar_carrinhos_abandonados()
    pedido = pedido_atual_do_usuario(current_user.id)
    
    if not pedido or pedido.itens == '[]': 
        return jsonify({"sucesso": False, "mensagem": "Sua reserva expirou (30 minutos) e os itens voltaram ao estoque. Verifique sua sacola, pois algum produto pode ter esgotado."})

    endereco_selecionado = session.get('endereco_envio_selecionado')
    if endereco_selecionado:
        pedido.endereco = endereco_selecionado

    itens_reservados = json.loads(pedido.itens)
    for item in itens_reservados:
        produto = db.session.get(Produto, item.get('id'))
        if produto and not produto.ativo:
            return jsonify({"sucesso": False, "mensagem": f"O produto '{produto.nome}' está inativo e não pode ser comprado."}), 409
    subtotal_centavos = sum(round(float(i['preco']) * 100) * int(i['quantidade']) for i in itens_reservados)
    subtotal = subtotal_centavos / 100
    if subtotal < VALOR_MINIMO_ATACADO and not current_user.pedido_sem_minimo:
        return jsonify({"sucesso": False, "mensagem": f"Para finalizar a compra, o pedido mínimo é de R$ {VALOR_MINIMO_ATACADO:,.2f}. Adicione mais produtos ao carrinho."})

    dados = request.get_json(silent=True) or {}
    frete_tipo = str(dados.get('frete_tipo') or pedido.frete_tipo or '').strip()
    if frete_tipo not in {'Correios', 'Excursão', 'Retirada em Surubim'}:
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

    pedido.frete_tipo = frete_tipo
    pedido.valor_total = subtotal
    pedido.frete_estimado = frete
    pedido.observacao = observacao.strip() or None
    if frete_tipo == 'Retirada em Surubim':
        pedido.endereco = 'Retirada em Surubim'

    if current_user.cliente_especial:
        if frete_tipo == 'Excursão':
            descricao_frete = f'Taxa de excursão: R$ {frete:.2f} (incluída no pagamento)'
            total_pagamento = subtotal + frete
        elif frete_tipo == 'Correios':
            descricao_frete = f'Frete dos Correios: R$ {frete:.2f} (pago à parte)'
            total_pagamento = subtotal
        else:
            descricao_frete = 'Retirada em Surubim: sem custo'
            total_pagamento = subtotal
        linhas_pedido = [
            f'Olá! Sou {current_user.nome} e gostaria de finalizar o pedido #{pedido.id}:',
            '',
            *[
                f"{int(item['quantidade'])}x {item['nome']} - Tam. {item['tamanho']} - R$ {float(item['preco']) * int(item['quantidade']):.2f}"
                for item in itens_reservados
            ],
            '',
            f'Subtotal: R$ {subtotal:.2f}',
            descricao_frete,
            f'Total para pagamento: R$ {total_pagamento:.2f}',
            f'Observação: {observacao.strip() or "Nenhuma"}',
            '',
            'Pagamento: fora do site (cliente especial)',
        ]
        pedido.status = 'PAGO'
        pedido.forma_pagamento = 'FORA_DO_SITE'
        pedido.data_atualizacao = datetime.utcnow()
        pedido.data_pagamento = pedido.data_atualizacao
        if pedido.numero_separacao is None:
            garantir_numero_separacao(pedido)
        db.session.commit()
        session.pop('endereco_envio_selecionado', None)
        numero_loja = re.sub(r'\D', '', str(current_app.config.get('WHATSAPP_LOJA', '5581999475717')))
        url_whatsapp = f"https://wa.me/{numero_loja}?text={requests.utils.quote(chr(10).join(linhas_pedido))}"
        return jsonify({"sucesso": True, "url_whatsapp": url_whatsapp, "status": 'PAGO', "mostrar_paga_fora_do_site": True})

    access_token = os.environ.get('MERCADO_PAGO_ACCESS_TOKEN') or current_app.config.get('MERCADO_PAGO_ACCESS_TOKEN', '')
    access_token = str(access_token or '').strip()
    if not access_token:
        return jsonify({"sucesso": False, "mensagem": "Mercado Pago não configurado. Defina MERCADO_PAGO_ACCESS_TOKEN para habilitar pagamentos."}), 503

    token_de_teste = access_token.upper().startswith('TEST-')
    campo_url_checkout = 'sandbox_init_point' if token_de_teste else 'init_point'
    itens_mercado_pago = [{
        'title': f"{item['nome']} (Tam: {item['tamanho']})",
        'quantity': int(item['quantidade']),
        'currency_id': 'BRL',
        'unit_price': round(float(item['preco']), 2),
    } for item in itens_reservados]
    if frete_tipo == 'Excursão':
        itens_mercado_pago.append({
            'title': 'Taxa de excursão',
            'quantity': 1,
            'currency_id': 'BRL',
            'unit_price': round(frete, 2),
        })
    pagador = {'name': current_user.nome}
    if current_user.email and not current_user.email.casefold().endswith('@clientes.leyly.local'):
        pagador['email'] = current_user.email
    raiz_site = request.url_root.rstrip('/')
    payload_mercado_pago = {
        'items': itens_mercado_pago,
        'external_reference': str(pedido.id),
        'payer': pagador,
        'back_urls': {
            'success': raiz_site,
            'failure': raiz_site,
            'pending': raiz_site,
        },
        'notification_url': f'{raiz_site}/api/mercadopago/webhook',
        'auto_return': 'approved',
    }

    try:
        resposta_mp = requests.post(
            'https://api.mercadopago.com/checkout/preferences',
            json=payload_mercado_pago,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=20,
        )
    except requests.RequestException:
        return jsonify({"sucesso": False, "mensagem": "Não foi possível conectar ao Mercado Pago. Tente novamente."}), 502

    try:
        dados_mp = resposta_mp.json() or {}
    except ValueError:
        dados_mp = {}
    if resposta_mp.status_code not in (200, 201):
        mensagem_mp = dados_mp.get('message') or dados_mp.get('error')
        return jsonify({"sucesso": False, "mensagem": mensagem_mp or f"O Mercado Pago recusou a preferência (HTTP {resposta_mp.status_code})."}), 502

    url_pagamento = dados_mp.get(campo_url_checkout)
    if not url_pagamento:
        ambiente = 'de teste' if token_de_teste else 'de produção'
        return jsonify({"sucesso": False, "mensagem": f"O Mercado Pago não retornou a URL de pagamento {ambiente}. Confira o token configurado."}), 502

    pedido.status = 'PAGAMENTO'
    pedido.data_atualizacao = datetime.utcnow()
    db.session.commit()
    session.pop('endereco_envio_selecionado', None)
    return jsonify({"sucesso": True, "url_pagamento": url_pagamento})

@main_bp.route('/api/mercadopago/webhook', methods=['POST', 'GET'])
def webhook_mercadopago():
    dados = request.get_json(silent=True) or {}
    dados_pagamento = dados.get('data') if isinstance(dados.get('data'), dict) else {}
    payment_id = request.args.get('data.id') or request.args.get('id') or dados_pagamento.get('id')
    if not payment_id:
        return jsonify({"status": "received"}), 200

    access_token = os.environ.get('MERCADO_PAGO_ACCESS_TOKEN') or current_app.config.get('MERCADO_PAGO_ACCESS_TOKEN', '')
    access_token = str(access_token or '').strip()
    if not access_token:
        return jsonify({"sucesso": False, "mensagem": "Mercado Pago não configurado."}), 503

    try:
        resposta_mp = requests.get(
            f'https://api.mercadopago.com/v1/payments/{payment_id}',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10,
        )
    except requests.RequestException:
        return jsonify({"sucesso": False, "mensagem": "Não foi possível consultar o pagamento."}), 502
    if resposta_mp.status_code != 200:
        return jsonify({"sucesso": False, "mensagem": "Não foi possível validar o pagamento."}), 502

    pagamento = resposta_mp.json()
    if pagamento.get('status') == 'approved' and pagamento.get('currency_id') == 'BRL':
        try:
            pedido_id = int(pagamento.get('external_reference'))
            valor_pago_centavos = round(float(pagamento.get('transaction_amount')) * 100)
        except (TypeError, ValueError):
            return jsonify({"status": "received"}), 200

        pedido = db.session.get(Pedido, pedido_id)
        if pedido and pedido.status == 'PAGAMENTO':
            itens_pedido = json.loads(pedido.itens or '[]')
            subtotal_centavos = sum(
                round(float(item['preco']) * 100) * int(item['quantidade'])
                for item in itens_pedido
            )
            frete_centavos = round(float(pedido.frete_estimado or 0) * 100)
            if pedido.frete_tipo == 'Excursão':
                valores_esperados = {subtotal_centavos + frete_centavos}
            elif pedido.frete_tipo == 'Correios':
                valores_esperados = {subtotal_centavos, subtotal_centavos + frete_centavos}
            else:
                valores_esperados = {subtotal_centavos}
            if valor_pago_centavos in valores_esperados:
                pedido.status = 'PAGO'
                garantir_numero_separacao(pedido)
                pedido.data_atualizacao = datetime.utcnow()
                pedido.data_pagamento = pedido.data_atualizacao
                db.session.commit()

    return jsonify({"status": "received"}), 200