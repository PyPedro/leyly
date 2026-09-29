import argparse
import json
import re
import sys
import unicodedata
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from app import create_app, db
from app.models import ImportacaoEstoque, Produto


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_FILE = ROOT / 'data' / 'inventario-inicial.txt'
IMPORT_KEY = 'inventario-inicial-2026-09-v2'
SIZES = {'P', 'M', 'G', 'GG', 'GG1', 'GG2'}
HEADER_PATTERN = re.compile(r'^(?P<nome>.+?)\s+(?:ref\s+)*(?P<ref>\d{3,4})\s*$', re.IGNORECASE)
STOCK_PATTERN = re.compile(r'^(\d+)\s*(.+)$')
ZERO_PATTERN = re.compile(r'^zerou$', re.IGNORECASE)
CORES_CANONICAS = {
    'açaí': 'Açaí', 'amarelo manteiga': 'Amarelo manteiga', 'azul': 'Azul', 'azul bebê': 'Azul bebê',
    'azul marinho': 'Azul marinho', 'azul neblina': 'Azul neblina', 'azul royal': 'Azul royal',
    'azul turquesa': 'Azul turquesa', 'bege': 'Bege', 'bordô': 'Bordô', 'branco': 'Branco',
    'caramelo': 'Caramelo', 'cacau': 'Cacau', 'cinza': 'Cinza', 'fúcsia': 'Fúcsia', 'grafite': 'Grafite',
    'laranja': 'Laranja', 'lilás': 'Lilás', 'marrom': 'Marrom', 'marsala': 'Marsala', 'mostarda': 'Mostarda',
    'nude': 'Nude', 'office white': 'Office white', 'pink cereja': 'Pink cereja', 'preto': 'Preto',
    'rosa bebê': 'Rosa bebê', 'rosa pink': 'Rosa pink', 'rosa quente': 'Rosa quente', 'rosé': 'Rosé',
    'telha': 'Telha', 'terracota': 'Terracota', 'uva': 'Uva', 'verde': 'Verde', 'verde água': 'Verde água',
    'verde jade': 'Verde jade', 'verde limão': 'Verde limão', 'verde militar': 'Verde militar',
    'verde musgo': 'Verde musgo', 'vinho': 'Vinho', 'roxo': 'Roxo',
}


def texto_chave(value):
    value = unicodedata.normalize('NFKD', str(value or ''))
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return re.sub(r'\s+', ' ', value).strip().casefold()


def normalizar_nome_cor(value):
    texto = re.sub(r'\s+', ' ', str(value or '').strip())
    if not texto:
        return ''
    chave = texto_chave(texto)
    nome_canonico = CORES_CANONICAS.get(chave)
    if nome_canonico:
        return nome_canonico
    return texto[:1].upper() + texto[1:]


def referencia_chave(value):
    digits = re.sub(r'\D', '', str(value or ''))
    return digits if digits else ''


def ler_inventario(arquivo=None, gerar_referencia_ausente=False):
    if arquivo is None:
        fonte = INVENTORY_FILE
    elif hasattr(arquivo, 'read'):
        fonte = arquivo
    else:
        fonte = arquivo

    if hasattr(fonte, 'read'):
        dados = fonte.read()
        if isinstance(dados, bytes):
            texto = dados.decode('utf-8')
        else:
            texto = str(dados)
    else:
        texto = Path(fonte).read_text(encoding='utf-8')

    produtos = OrderedDict()
    produto_atual = None
    tamanho_atual = None
    quantidade_pendente = None
    ignorar_bloco = False
    referencias_sinteticas = set()
    indice_referencia_sintetica = 0

    def gerar_referencia_sintetica():
        nonlocal indice_referencia_sintetica
        while True:
            indice_referencia_sintetica += 1
            referencia = '0' * indice_referencia_sintetica
            if referencia not in referencias_sinteticas and referencia not in produtos:
                referencias_sinteticas.add(referencia)
                return referencia

    def finalizar_produto():
        nonlocal produto_atual, tamanho_atual, quantidade_pendente, ignorar_bloco
        if produto_atual is None:
            return
        referencia = referencia_chave(produto_atual.get('referencia'))
        if not referencia:
            if gerar_referencia_ausente:
                referencia = gerar_referencia_sintetica()
            else:
                produto_atual = None
                tamanho_atual = None
                quantidade_pendente = None
                ignorar_bloco = False
                return

        produto_atual['referencia'] = referencia
        anterior = produtos.get(referencia)
        if anterior is None:
            produtos[referencia] = produto_atual.copy()
            quantidade_pendente = None
            return

        for nome_tamanho, cores in produto_atual['estoque'].items():
            estoque_anterior = anterior['estoque'].setdefault(nome_tamanho, OrderedDict())
            for cor, quantidade in cores.items():
                chave_cor = texto_chave(cor)
                cor_existente = next((nome for nome in estoque_anterior if texto_chave(nome) == chave_cor), None)
                if cor_existente is None:
                    estoque_anterior[cor] = quantidade
                else:
                    estoque_anterior[cor_existente] += quantidade

        if not anterior['nome']:
            anterior['nome'] = produto_atual['nome']
        quantidade_pendente = None

    for numero, linha_original in enumerate(texto.splitlines(), start=1):
        linha = linha_original.strip()
        if not linha or linha.startswith('#'):
            continue

        if ignorar_bloco:
            cabecalho = HEADER_PATTERN.fullmatch(linha)
            if cabecalho:
                ignorar_bloco = False
            else:
                continue

        cabecalho = HEADER_PATTERN.fullmatch(linha)
        if cabecalho:
            finalizar_produto()
            produto_atual = {
                'nome': cabecalho.group('nome').strip(),
                'referencia': referencia_chave(cabecalho.group('ref')),
                'estoque': OrderedDict(),
            }
            tamanho_atual = None
            quantidade_pendente = None
            ignorar_bloco = False
            continue

        if produto_atual is None:
            if (
                not linha.upper() in SIZES
                and not ZERO_PATTERN.fullmatch(linha)
                and not linha.isdigit()
                and not STOCK_PATTERN.fullmatch(linha)
                and not HEADER_PATTERN.fullmatch(linha)
            ):
                produto_atual = {
                    'nome': linha,
                    'referencia': '',
                    'estoque': OrderedDict(),
                }
                tamanho_atual = None
                quantidade_pendente = None
                ignorar_bloco = False
                continue
            raise ValueError(f'Linha {numero}: esperava nome e referencia do produto.')

        if tamanho_atual is not None and quantidade_pendente is None and re.match(r'^[A-Za-zÀ-ÿ]', linha) and not linha.upper() in SIZES and not ZERO_PATTERN.fullmatch(linha) and not STOCK_PATTERN.fullmatch(linha):
            finalizar_produto()
            produto_atual = {
                'nome': linha,
                'referencia': '',
                'estoque': OrderedDict(),
            }
            tamanho_atual = None
            quantidade_pendente = None
            ignorar_bloco = False
            continue

        if linha.upper() in SIZES:
            tamanho_atual = linha.upper()
            produto_atual['estoque'].setdefault(tamanho_atual, OrderedDict())
            quantidade_pendente = None
            continue

        if ZERO_PATTERN.fullmatch(linha) or linha == '0':
            if tamanho_atual is None:
                raise ValueError(f'Linha {numero}: "Zerou" ou "0" sem tamanho ativo: {linha_original!r}.')
            produto_atual['estoque'].setdefault(tamanho_atual, OrderedDict())
            quantidade_pendente = None
            continue

        item = STOCK_PATTERN.fullmatch(linha)
        if item and tamanho_atual is not None:
            quantidade = int(item.group(1))
            cor = normalizar_nome_cor(re.sub(r'\s+', ' ', item.group(2).strip().rstrip('.')).strip())
            if not cor or quantidade < 0:
                raise ValueError(f'Linha {numero}: cor ou quantidade invalida.')
            estoque_cor = produto_atual['estoque'][tamanho_atual]
            chave_cor = texto_chave(cor)
            cor_existente = next((nome for nome in estoque_cor if texto_chave(nome) == chave_cor), None)
            if cor_existente is None:
                estoque_cor[cor] = quantidade
            else:
                estoque_cor[cor_existente] += quantidade
            quantidade_pendente = None
            continue

        if quantidade_pendente is not None and tamanho_atual is not None:
            cor = normalizar_nome_cor(re.sub(r'\s+', ' ', linha.strip().rstrip('.')).strip())
            if not cor:
                raise ValueError(f'Linha {numero}: cor invalida para quantidade pendente.')
            estoque_cor = produto_atual['estoque'][tamanho_atual]
            chave_cor = texto_chave(cor)
            cor_existente = next((nome for nome in estoque_cor if texto_chave(nome) == chave_cor), None)
            if cor_existente is None:
                estoque_cor[cor] = quantidade_pendente
            else:
                estoque_cor[cor_existente] += quantidade_pendente
            quantidade_pendente = None
            continue

        if linha.isdigit() and tamanho_atual is not None:
            quantidade_pendente = int(linha)
            continue

        if tamanho_atual is None and not any(ch.isdigit() for ch in linha):
            finalizar_produto()
            produto_atual = None
            tamanho_atual = None
            ignorar_bloco = True
            continue

        raise ValueError(f'Linha {numero}: linha de estoque invalida: {linha_original!r}.')

    finalizar_produto()
    return list(produtos.values())


def localizar_produto(produtos_db, item):
    referencia_item = referencia_chave(item['referencia'])
    por_referencia = [
        produto for produto in produtos_db
        if referencia_chave(produto.codigo) == referencia_item
    ]
    if len(por_referencia) == 1:
        return por_referencia[0], 'referencia'
    if len(por_referencia) > 1:
        return None, 'referencia duplicada no catalogo'

    por_nome = [produto for produto in produtos_db if texto_chave(produto.nome) == texto_chave(item['nome'])]
    if len(por_nome) == 1:
        return por_nome[0], 'nome exato (codigo divergente)'
    if len(por_nome) > 1:
        return None, 'nome ambiguo e referencia ausente'
    return None, 'produto ausente'


def montar_variantes(produto, item):
    variantes_anteriores = produto.variantes_config
    precos_anteriores = {}
    precos_por_tamanho = {}
    for variante in variantes_anteriores:
        for tamanho in variante.get('tamanhos', []):
            chave = (texto_chave(variante.get('cor')), texto_chave(tamanho.get('nome')))
            precos_anteriores[chave] = tamanho.get('preco')
            precos_por_tamanho.setdefault(texto_chave(tamanho.get('nome')), tamanho.get('preco'))
    for tamanho in produto.grade_config:
        precos_por_tamanho.setdefault(texto_chave(tamanho.get('nome')), tamanho.get('preco'))

    variantes = OrderedDict()
    for nome_tamanho, cores in item['estoque'].items():
        for cor, quantidade in cores.items():
            tamanhos = variantes.setdefault(cor, [])
            chave_preco = (texto_chave(cor), texto_chave(nome_tamanho))
            preco = precos_anteriores.get(chave_preco)
            if preco is None:
                preco = precos_por_tamanho.get(texto_chave(nome_tamanho))
            if preco is None:
                preco = produto.preco
            tamanhos.append({
                'nome': nome_tamanho,
                'estoque': quantidade,
                'preco': float(preco),
            })

    return [{'cor': cor, 'tamanhos': tamanhos} for cor, tamanhos in variantes.items()]


def aplicar_estoque_produto(produto, item):
    variantes = montar_variantes(produto, item)
    produto.variantes = json.dumps(variantes, ensure_ascii=False)
    produto.cores = json.dumps([variante['cor'] for variante in variantes], ensure_ascii=False)
    produto.grade = json.dumps(variantes[0]['tamanhos'] if variantes else [], ensure_ascii=False)
    for tamanho in ('p', 'm', 'g', 'gg'):
        tamanhos_resumo = {'gg', 'gg2'} if tamanho == 'gg' else {tamanho}
        setattr(produto, f'estoque_{tamanho}', sum(
            int(item_tamanho['estoque'])
            for variante in variantes
            for item_tamanho in variante['tamanhos']
            if item_tamanho['nome'].casefold() in tamanhos_resumo
        ))


def criar_produto_sem_cadastro(item):
    produto = Produto(
        codigo=item['referencia'],
        nome=item['nome'],
        preco=0.0,
        etiqueta='NOVO',
        imagem_url='',
        estoque_p=0,
        estoque_m=0,
        estoque_g=0,
        estoque_gg=0,
    )
    aplicar_estoque_produto(produto, item)
    return produto


def planejar_importacao(produtos_db, inventario):
    correspondencias = []
    problemas = []
    for item in inventario:
        produto, metodo = localizar_produto(produtos_db, item)
        if produto is None and metodo == 'produto ausente':
            correspondencias.append((item, None, 'novo produto'))
        elif produto is None:
            problemas.append(f"Ref {item['referencia']} ({item['nome']}): {metodo}.")
        else:
            correspondencias.append((item, produto, metodo))
    return correspondencias, problemas


def executar_importacao(app=None, aplicar=True, arquivo=None, gerar_referencia_ausente=False):
    app = app or create_app()
    with app.app_context():
        inventario = ler_inventario(arquivo, gerar_referencia_ausente=gerar_referencia_ausente)
        if arquivo is None and db.session.get(ImportacaoEstoque, IMPORT_KEY):
            return {
                'sucesso': True,
                'importada': False,
                'mensagem': f'Importacao {IMPORT_KEY} ja executada; nenhuma alteracao feita.',
                'produtos': Produto.query.count(),
            }

        produtos_db = Produto.query.all()
        correspondencias, problemas = planejar_importacao(produtos_db, inventario)

        if problemas:
            return {
                'sucesso': False,
                'importada': False,
                'mensagem': 'Importacao cancelada; referencias sem correspondencia unica.',
                'problemas': problemas,
                'produtos': len(inventario),
            }

        if not aplicar:
            return {
                'sucesso': True,
                'importada': False,
                'mensagem': 'Validacao concluida sem gravar. Execute com --apply para importar uma unica vez.',
                'produtos': len(correspondencias),
            }

        try:
            for item, produto, _ in correspondencias:
                if produto is None:
                    produto = criar_produto_sem_cadastro(item)
                    db.session.add(produto)
                else:
                    aplicar_estoque_produto(produto, item)

            db.session.add(ImportacaoEstoque(chave=f'{IMPORT_KEY}-{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")}' ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        return {
            'sucesso': True,
            'importada': True,
            'mensagem': f'Importacao concluida: {len(correspondencias)} produtos atualizados.',
            'produtos': len(correspondencias),
        }


def main():
    parser = argparse.ArgumentParser(description='Importa o estoque inicial por referencia, cor e tamanho.')
    parser.add_argument('--apply', action='store_true', help='Grava no banco; sem esta opcao, apenas valida.')
    args = parser.parse_args()

    app = create_app()
    resultado = executar_importacao(app=app, aplicar=args.apply)
    print(f'Produtos na importacao: {resultado.get("produtos", 0)}')
    if not resultado['sucesso']:
        print(resultado['mensagem'])
        for problema in resultado.get('problemas', []):
            print(f'- {problema}')
        return 2

    print(resultado['mensagem'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
