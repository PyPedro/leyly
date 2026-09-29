import json
import sys
from collections import OrderedDict
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import FileStorage

from app import configurar_diretorio_uploads, create_app, db
from app.models import ImportacaoEstoque, Pedido, Produto, ProdutoImagem, Usuario
from scripts import importar_estoque
from scripts.importar_estoque import criar_produto_sem_cadastro, ler_inventario, planejar_importacao
from app.routes import chave_cor, cor_para_hex, imagem_disponivel, nome_cor, validar_arquivos_imagem, variantes_com_cor_hex


def test_inventario_inicial_tem_referencias_unicas_e_total_esperado():
    inventario = ler_inventario()

    assert len(inventario) == 60
    assert sum(item['referencia'] == '459' for item in inventario) == 1
    assert sum(
        quantidade
        for item in inventario
        for cores in item['estoque'].values()
        for quantidade in cores.values()
    ) == 6704


def test_configurar_uploads_migra_arquivos_legados_sem_sobrescrever_disco(tmp_path, monkeypatch):
    diretorio_estatico = tmp_path / 'static' / 'uploads'
    diretorio_persistente = tmp_path / 'disk' / 'uploads'
    links_criados = []
    diretorio_estatico.mkdir(parents=True)
    diretorio_persistente.mkdir(parents=True)
    (diretorio_estatico / 'imagem-antiga.jpg').write_bytes(b'legado')
    (diretorio_persistente / 'imagem-existente.jpg').write_bytes(b'persistente')
    (diretorio_estatico / 'imagem-existente.jpg').write_bytes(b'versao-do-repositorio')
    monkeypatch.setattr(
        'app.os.symlink',
        lambda destino, origem, target_is_directory: links_criados.append((destino, origem)),
    )

    configurar_diretorio_uploads(str(diretorio_estatico), str(diretorio_persistente), migrar_existentes=True)

    assert links_criados == [(str(diretorio_persistente), str(diretorio_estatico))]
    assert not diretorio_estatico.exists()
    assert (diretorio_persistente / 'imagem-antiga.jpg').read_bytes() == b'legado'
    assert (diretorio_persistente / 'imagem-existente.jpg').read_bytes() == b'persistente'


def test_inventario_soma_cores_repetidas_e_preserva_tamanho_especial():
    inventario = {item['referencia']: item for item in ler_inventario()}

    assert inventario['523']['estoque']['M']['Açaí'] == 8
    assert inventario['461']['estoque']['M']['Caramelo'] == 10
    assert inventario['366']['estoque']['GG2']['Branco'] == 19
    assert inventario['382']['estoque']['G']['Terracota'] == 12


def test_ler_inventario_aceita_zerou_e_quantidade_em_linha_separada(monkeypatch, tmp_path):
    arquivo = tmp_path / 'inventario.txt'
    arquivo.write_text(
        'Conj teste Ref 999\n'
        'M\n'
        'Zerou\n'
        'G\n'
        '9\n'
        'Azul marinho\n'
        '3\n'
        'Preto\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(importar_estoque, 'INVENTORY_FILE', arquivo)

    inventario = importar_estoque.ler_inventario()

    assert inventario == [{
        'nome': 'Conj teste',
        'referencia': '999',
        'estoque': {'M': OrderedDict(), 'G': {'Azul marinho': 9, 'Preto': 3}},
    }]


def test_ler_inventario_aceita_cabecalhos_e_cores_no_formato_enviado_pelo_usuario(monkeypatch, tmp_path):
    arquivo = tmp_path / 'inventario.txt'
    arquivo.write_text(
        'Top 2 tiras de viés\n'
        'M\n'
        '7 rosé\n'
        '3Azul marinho\n'
        'G\n'
        'Zerou\n'
        'Conj short e top e tiara ref 518\n'
        'M\n'
        '1 caramelo\n'
        'G\n'
        '0\n'
        'Conj short duplo e top Ref ref 410\n'
        'M\n'
        '1 Pink cereja\n'
        '11rosé\n'
        'G\n'
        '2 preto\n'
        '3Azul marinho\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(importar_estoque, 'INVENTORY_FILE', arquivo)

    inventario = importar_estoque.ler_inventario()
    por_ref = {item['referencia']: item for item in inventario}

    assert '518' in por_ref
    assert por_ref['518']['estoque']['M']['Caramelo'] == 1
    assert por_ref['410']['estoque']['M']['Pink cereja'] == 1
    assert por_ref['410']['estoque']['M']['Rosé'] == 11
    assert por_ref['410']['estoque']['G']['Azul marinho'] == 3
    assert por_ref['410']['estoque']['G']['Preto'] == 2


def test_ler_inventario_cria_referencia_sintetica_para_itens_sem_referencia(monkeypatch, tmp_path):
    arquivo = tmp_path / 'inventario.txt'
    arquivo.write_text(
        'Top 2 tiras de viés\n'
        'M\n'
        '7 rosé\n'
        'G\n'
        '3 Azul marinho\n'
        'Conj short e top e tiara ref 518\n'
        'M\n'
        '1 caramelo\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(importar_estoque, 'INVENTORY_FILE', arquivo)

    inventario = importar_estoque.ler_inventario(gerar_referencia_ausente=True)
    assert {item['referencia'] for item in inventario} == {'0', '518'}
    assert inventario[0]['nome'] == 'Top 2 tiras de viés'
    assert inventario[0]['estoque']['M']['Rosé'] == 7
    assert inventario[0]['estoque']['G']['Azul marinho'] == 3


def test_cores_nomeadas_preservam_cor_de_pedidos_legados():
    assert cor_para_hex('Pink Cereja') == '#c51e62'
    assert nome_cor('#1c1c1a') == 'Preto'
    assert chave_cor('#172b4d') == chave_cor('Azul marinho')
    assert nome_cor('#123456') == 'Personalizada (#123456)'
    variante = variantes_com_cor_hex([{'cor': 'Azul marinho', 'tamanhos': []}])[0]
    assert variante['cor'] == 'Azul marinho'
    assert variante['cor_hex'] == '#172b4d'
    assert variante['cor_nome'] == 'Azul marinho'


def test_cria_produto_novo_com_preco_zero_sem_imagem_e_grade_completa():
    inventario = {item['referencia']: item for item in ler_inventario()}
    produto = criar_produto_sem_cadastro(inventario['366'])

    assert produto.codigo == '366'
    assert produto.nome == 'Short duplo plus size'
    assert produto.preco == 0
    assert produto.imagem_url == ''
    assert produto.estoque_gg == 19
    assert {'cor': 'Branco', 'tamanhos': [{'nome': 'GG2', 'estoque': 19, 'preco': 0.0}]} in json.loads(produto.variantes)


def test_edicao_do_preco_base_atualiza_precos_das_variantes(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    produto = Produto(
        codigo='PRECO-TESTE',
        nome='Calça Flare',
        preco=0,
        etiqueta='NOVO',
        imagem_url='',
        variantes=json.dumps([{'cor': 'Preto', 'tamanhos': [
            {'nome': 'M', 'estoque': 8, 'preco': 0},
            {'nome': 'G', 'estoque': 4, 'preco': 75},
        ]}]),
    )
    with app.app_context():
        db.session.add(produto)
        db.session.commit()
        produto_id = produto.id
        variantes = json.loads(produto.variantes)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post(f'/api/admin/produtos/editar/{produto_id}', data={
            'codigo': 'PRECO-TESTE',
            'nome': 'Calça Flare',
            'preco': '59.90',
            'variantes': json.dumps(variantes),
        })

    assert resposta.get_json()['sucesso'] is True
    with app.app_context():
        produto_atualizado = db.session.get(Produto, produto_id)
        precos = {tamanho['nome']: tamanho['preco'] for tamanho in json.loads(produto_atualizado.variantes)[0]['tamanhos']}
        assert precos == {'M': 59.9, 'G': 75}


def test_sync_carrinho_usa_preco_do_catalogo_e_calcula_total(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    monkeypatch.delenv('WHATSAPP_LOJA', raising=False)
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        usuario = Usuario(nome='Cliente', email='cliente-preco@leyly.com', senha='hash', whatsapp='5581999999999', cliente_especial=True)
        produto = Produto(
            codigo='CARRINHO-PRECO',
            nome='Calça Flare',
            preco=200,
            etiqueta='NOVO',
            imagem_url='',
            variantes=json.dumps([{'cor': 'Preto', 'tamanhos': [{'nome': 'M', 'estoque': 5, 'preco': 200}]}]),
        )
        db.session.add_all([usuario, produto])
        db.session.commit()
        usuario_id = usuario.id
        produto_id = produto.id

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(usuario_id)
            sess['_fresh'] = True
        resposta = client.post('/api/carrinho/sync', json={'carrinho': [{
            'id': produto_id,
            'nome': 'Calça Flare',
            'cor': 'Preto',
            'tamanho': 'M',
            'quantidade': 2,
            'preco': 0,
        }]})
        checkout = client.post('/checkout-infinitepay', json={'frete': 15})

    assert resposta.get_json()['sucesso'] is True
    dados_checkout = checkout.get_json()
    assert dados_checkout['sucesso'] is True
    assert 'wa.me/558199475717' in dados_checkout['url_whatsapp']
    with app.app_context():
        pedido = Pedido.query.one()
        assert json.loads(pedido.itens)[0]['preco'] == 200
        assert pedido.valor_total == 415


def test_admin_destaca_promocao_e_produto_aparece_antes_na_vitrine(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        promocao = Produto(codigo='PROMO', nome='Z Produto em oferta', preco=50, etiqueta='NOVO', imagem_url='')
        comum = Produto(codigo='COMUM', nome='A Produto comum', preco=60, etiqueta='NOVO', imagem_url='')
        db.session.add_all([promocao, comum])
        db.session.commit()
        promocao_id = promocao.id

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post(f'/api/admin/produtos/{promocao_id}/promocao', json={'promocao': True})
        assert resposta.status_code == 200
        assert resposta.get_json()['promocao'] is True
        assert next(item for item in client.get('/api/admin/produtos').get_json() if item['id'] == promocao_id)['promocao'] is True
        html = client.get('/').get_data(as_text=True)

    assert html.index('Z Produto em oferta') < html.index('A Produto comum')
    assert 'PROMOÇÃO' in html


def test_frete_considera_cep_de_origem_e_peso_por_peca(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    monkeypatch.setenv('CEP_ORIGEM', '55750-000')
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        usuario = Usuario(nome='Cliente', email='cliente-frete@leyly.com', senha='hash', whatsapp='5581999999999')
        db.session.add(usuario)
        db.session.commit()
        usuario_id = usuario.id

    consultas = []

    def consultar_cep(url, timeout):
        consultas.append(url)
        dados = {'uf': 'PE', 'localidade': 'Origem'} if '55750000' in url else {'uf': 'SP', 'localidade': 'Destino'}
        return SimpleNamespace(status_code=200, json=lambda: dados)

    monkeypatch.setattr('app.routes.requests.get', consultar_cep)
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(usuario_id)
            sess['_fresh'] = True
        resposta = client.post('/calcular-frete', json={
            'cep': '01001-000',
            'carrinho': [{'quantidade': 3}],
        })

    dados = resposta.get_json()
    assert dados['sucesso'] is True
    assert dados['cep_origem'] == '55750-000'
    assert dados['peso_gramas'] == 1200
    assert dados['opcoes'][0]['valor'] == 33.0
    assert any('55750000' in consulta for consulta in consultas)


def test_whatsapp_da_loja_usa_o_numero_informado(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    monkeypatch.delenv('WHATSAPP_LOJA', raising=False)
    app = create_app()

    assert app.config['WHATSAPP_LOJA'] == '558199475717'


def test_login_google_cria_conta_com_email_verificado(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True

    class ClienteGoogleFalso:
        def authorize_access_token(self):
            return {'userinfo': {
                'sub': 'google-sub-123',
                'email': 'Cliente@Gmail.com',
                'email_verified': True,
                'name': 'Cliente Gmail',
            }}

    app.extensions['google_oauth'] = ClienteGoogleFalso()
    with app.test_client() as client:
        resposta = client.get('/login/google/callback')
        assert resposta.status_code == 302
        pagina = client.get('/').get_data(as_text=True)

    assert 'OLÁ, CLIENTE (SAIR)' in pagina
    with app.app_context():
        usuario = Usuario.query.filter_by(email='cliente@gmail.com').one()
        assert usuario.google_sub == 'google-sub-123'
        assert usuario.whatsapp is None


def test_login_google_vincula_conta_existente_pelo_email_verificado(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    with app.app_context():
        usuario = Usuario(nome='Cliente Existente', email='cliente@gmail.com', senha='hash')
        db.session.add(usuario)
        db.session.commit()
        usuario_id = usuario.id

    class ClienteGoogleFalso:
        def authorize_access_token(self):
            return {'userinfo': {
                'sub': 'google-sub-existente',
                'email': 'CLIENTE@gmail.com',
                'email_verified': True,
                'name': 'Cliente Existente',
            }}

    app.extensions['google_oauth'] = ClienteGoogleFalso()
    with app.test_client() as client:
        resposta = client.get('/login/google/callback')
        assert resposta.status_code == 302
        pagina = client.get('/').get_data(as_text=True)

    assert 'OLÁ, CLIENTE (SAIR)' in pagina
    with app.app_context():
        assert Usuario.query.count() == 1
        usuario = db.session.get(Usuario, usuario_id)
        assert usuario.google_sub == 'google-sub-existente'
        assert usuario.senha == 'hash'


def test_login_google_nao_cria_conta_com_email_nao_verificado(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()

    class ClienteGoogleFalso:
        def authorize_access_token(self):
            return {'userinfo': {
                'sub': 'google-sub-nao-verificado',
                'email': 'nao-verificado@gmail.com',
                'email_verified': False,
                'name': 'Conta Inválida',
            }}

    app.extensions['google_oauth'] = ClienteGoogleFalso()
    with app.test_client() as client:
        resposta = client.get('/login/google/callback')
        assert resposta.status_code == 302
        pagina = client.get('/').get_data(as_text=True)

    assert 'não confirmou um e-mail válido' in pagina
    with app.app_context():
        assert Usuario.query.count() == 0


def test_botao_google_so_aparece_com_credenciais_configuradas(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'cliente-oauth-teste')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'segredo-oauth-teste')
    app = create_app()

    with app.test_client() as client:
        html = client.get('/').get_data(as_text=True)

    assert 'Continuar com Google' in html
    assert 'href="/login/google"' in html


def test_login_google_usa_callback_https_no_render(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['IS_RENDER'] = True

    class ClienteGoogleFalso:
        def authorize_redirect(self, redirect_uri):
            from flask import redirect
            return redirect(redirect_uri)

    app.extensions['google_oauth'] = ClienteGoogleFalso()
    with app.test_client() as client:
        resposta = client.get('/login/google')

    assert resposta.status_code == 302
    assert resposta.location == 'https://localhost/login/google/callback'


def test_catalogo_vazio_planeja_criacao_das_60_referencias():
    correspondencias, problemas = planejar_importacao([], ler_inventario())

    assert len(correspondencias) == 60
    assert not problemas
    assert all(produto is None and metodo == 'novo produto' for _, produto, metodo in correspondencias)


def test_vitrine_omite_imagens_antigas_ausentes_e_serve_banners(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    with app.app_context():
        db.session.add(Produto(
            codigo='473',
            nome='Conj short saia e top',
            preco=0,
            etiqueta='NOVO',
            imagem_url='uploads/arquivo-que-nao-existe.pdf',
            cores=json.dumps(['Azul marinho']),
            variantes=json.dumps([{'cor': 'Azul marinho', 'tamanhos': [{'nome': 'M', 'estoque': 7, 'preco': 0}]}]),
        ))
        produto = Produto.query.filter_by(codigo='473').one()
        db.session.add(ProdutoImagem(produto=produto, imagem_url='uploads/arquivo-que-nao-existe.pdf', ordem=0))
        db.session.commit()

    client = app.test_client()
    resposta = client.get('/')
    html = resposta.get_data(as_text=True)
    assert resposta.status_code == 200
    assert 'class="hero-section"' in html
    assert 'VER CATÁLOGO DE ATACADO' not in html
    assert 'ABASTEÇA.' not in html
    assert 'Foto não cadastrada' in html
    assert 'Preço pendente no estoque' in html
    assert 'src="/static/"' not in html
    assert 'arquivo-que-nao-existe.pdf' not in html
    assets = (
        'banner_hero1.jpeg', 'banner_macaquinho.jpeg', 'banner_lounge.jpeg',
        'cat_conjuntos.jpeg', 'cat_leggings.jpeg', 'cat_casacos.jpeg', 'cat_tops.jpeg',
    )
    assert all(client.get(f'/static/img/{asset}').status_code == 200 for asset in assets)


def test_vitrine_filtra_por_categoria_e_agrupa_por_nome(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()

    with app.app_context():
        db.session.add_all([
            Produto(codigo='001', nome='Conj short e top', preco=99.9, etiqueta='NOVO', imagem_url=''),
            Produto(codigo='002', nome='Conj short e top', preco=109.9, etiqueta='NOVO', imagem_url=''),
            Produto(codigo='003', nome='Top 2 tiras de viés', preco=69.9, etiqueta='NOVO', imagem_url=''),
            Produto(codigo='004', nome='Legging com bolso', preco=89.9, etiqueta='NOVO', imagem_url=''),
        ])
        db.session.commit()

    with app.test_client() as client:
        resposta = client.get('/?categoria=conjuntos')
        assert resposta.status_code == 200
        html = resposta.get_data(as_text=True)
        assert 'Conj short e top' in html
        assert 'Top 2 tiras de viés' not in html
        assert 'Legging com bolso' not in html
        assert html.count('class="product-card"') == 1


def test_api_cadastro_rejeita_pdf_sem_criar_produto(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post('/api/admin/produtos/cadastrar', data={
            'codigo': 'PDF-404',
            'nome': 'Arquivo inválido',
            'preco': '10',
            'grade': json.dumps([{'nome': 'M', 'estoque': 1, 'preco': 10}]),
            'cores': json.dumps(['Preto']),
            'variantes': json.dumps([{'cor': 'Preto', 'tamanhos': [{'nome': 'M', 'estoque': 1, 'preco': 10}]}]),
            'imagens': (BytesIO(b'%PDF-1.7 arquivo'), 'catalogo.pdf', 'application/pdf'),
        })

    assert resposta.status_code == 400
    assert 'somente imagens' in resposta.get_json()['mensagem']
    with app.app_context():
        assert Produto.query.filter_by(codigo='PDF-404').count() == 0


def test_apply_cria_60_produtos_e_nao_duplica_na_reexecucao(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    monkeypatch.setattr(importar_estoque, 'create_app', lambda: app)
    monkeypatch.setattr(sys, 'argv', ['scripts.importar_estoque', '--apply'])

    assert importar_estoque.main() == 0
    with app.app_context():
        assert Produto.query.count() == 60
        produto = Produto.query.filter_by(codigo='056').one()
        assert produto.preco == 0
        assert produto.imagem_url == ''
        assert ImportacaoEstoque.query.count() == 1

    assert importar_estoque.main() == 0
    with app.app_context():
        assert Produto.query.count() == 60


def test_importacao_por_arquivo_texto_adiciona_itens_novos(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    monkeypatch.setattr(importar_estoque, 'create_app', lambda: app)

    arquivo = tmp_path / 'lote-novo.txt'
    arquivo.write_text(
        'Conj teste lote novo Ref 999\n'
        'M\n'
        '2 Azul marinho\n'
        '1 Preto\n'
        'G\n'
        '3 Verde militar\n'
        '1 Rosé\n',
        encoding='utf-8',
    )

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post('/api/admin/importar-estoque', data={
            'arquivo': (arquivo.open('rb'), 'lote-novo.txt'),
        })

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados['sucesso'] is True
    assert dados['importada'] is True
    with app.app_context():
        produto = Produto.query.filter_by(codigo='999').first()
        assert produto is not None
        assert produto.estoque_m == 3
        assert produto.estoque_g == 4


def test_importacao_por_arquivo_texto_aceita_campo_arquivo_alternativo(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    monkeypatch.setattr(importar_estoque, 'create_app', lambda: app)

    arquivo = tmp_path / 'lote-alternativo.txt'
    arquivo.write_text(
        'Conj lote alternativo Ref 998\n'
        'M\n'
        '2 Azul marinho\n'
        '1 Preto\n',
        encoding='utf-8',
    )

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post('/api/admin/importar-estoque', data={
            'file': (arquivo.open('rb'), 'lote-alternativo.txt'),
        })

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados['sucesso'] is True
    assert dados['importada'] is True
    with app.app_context():
        produto = Produto.query.filter_by(codigo='998').first()
        assert produto is not None
        assert produto.estoque_m == 3


def test_importacao_por_arquivo_texto_pode_adicionar_referencia_nova_apos_importacao_inicial(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    monkeypatch.setattr(importar_estoque, 'create_app', lambda: app)

    with app.app_context():
        db.session.add(ImportacaoEstoque(chave=importar_estoque.IMPORT_KEY))
        db.session.commit()

    arquivo = tmp_path / 'lote-novo-ref-456.txt'
    arquivo.write_text(
        'Conj short saia e top e tiara ref 456\n'
        'M\n'
        '7 rosé\n'
        '3 Azul neblina\n'
        '1 verde militar\n'
        '2 grafite\n'
        'G\n'
        '9 Azul marinho\n',
        encoding='utf-8',
    )

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post('/api/admin/importar-estoque', data={
            'arquivo': (arquivo.open('rb'), 'lote-novo-ref-456.txt'),
        })

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados['sucesso'] is True
    assert dados['importada'] is True
    with app.app_context():
        produto = Produto.query.filter_by(codigo='456').first()
        assert produto is not None
        assert produto.nome == 'Conj short saia e top e tiara'
        assert produto.estoque_m == 13
        assert produto.estoque_g == 9


def test_api_importacao_em_lote_reutiliza_logica_de_estoque(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    monkeypatch.setattr(importar_estoque, 'create_app', lambda: app)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post('/api/admin/importar-estoque')

    assert resposta.status_code in (200, 400)
    dados = resposta.get_json()
    assert 'sucesso' in dados
    assert 'mensagem' in dados


def test_api_impede_referencia_duplicada_no_cadastro_e_na_edicao(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        db.session.add_all([
            Produto(codigo='REF-10', nome='Produto 10', preco=10, etiqueta='TESTE', imagem_url=''),
            Produto(codigo='REF-20', nome='Produto 20', preco=10, etiqueta='TESTE', imagem_url=''),
        ])
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        cadastro = client.post('/api/admin/produtos/cadastrar', data={'codigo': ' ref-10 ', 'nome': 'Cópia'})
        edicao = client.post('/api/admin/produtos/editar/2', data={'codigo': 'REF-10', 'nome': 'Produto 20'})

    assert cadastro.status_code == 409
    assert cadastro.get_json()['sucesso'] is False
    assert edicao.status_code == 409
    assert edicao.get_json()['sucesso'] is False


def test_indice_unico_do_banco_bloqueia_referencia_com_caixa_diferente(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    with app.app_context():
        db.session.add(Produto(codigo='REF-30', nome='Produto 30', preco=10, etiqueta='TESTE', imagem_url=''))
        db.session.commit()
        db.session.add(Produto(codigo='ref-30', nome='Duplicado', preco=10, etiqueta='TESTE', imagem_url=''))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        assert Produto.query.count() == 1


def test_uploads_rejeitam_pdf_e_arquivo_disfarçado_de_imagem():
    pdf = FileStorage(stream=BytesIO(b'%PDF-1.7 arquivo'), filename='catalogo.pdf', content_type='application/pdf')
    pdf_disfarçado = FileStorage(stream=BytesIO(b'%PDF-1.7 arquivo'), filename='catalogo.jpg', content_type='image/jpeg')

    with pytest.raises(ValueError, match='somente imagens'):
        validar_arquivos_imagem([pdf])
    with pytest.raises(ValueError, match='imagem válida'):
        validar_arquivos_imagem([pdf_disfarçado])


def test_upload_jpeg_valido_e_aceito_com_stream_rebobinado():
    conteudo = BytesIO()
    Image.new('RGB', (1, 1), color='red').save(conteudo, format='JPEG')
    conteudo.seek(0)
    upload = FileStorage(stream=conteudo, filename='produto.jpg', content_type='image/jpeg')

    assert validar_arquivos_imagem([upload]) == [upload]
    assert upload.stream.tell() == 0


def test_api_exclui_imagem_ativa_e_mantem_outra_imagem(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True

    with app.app_context():
        produto = Produto(
            codigo='IMG-77', nome='Produto com fotos', preco=99, etiqueta='TESTE', imagem_url='uploads/primeira.jpg'
        )
        db.session.add(produto)
        db.session.commit()
        img1 = ProdutoImagem(produto=produto, imagem_url='uploads/primeira.jpg', ordem=0)
        img2 = ProdutoImagem(produto=produto, imagem_url='uploads/segunda.jpg', ordem=1)
        db.session.add_all([img1, img2])
        db.session.commit()
        produto_id = produto.id
        imagem_id = img1.id

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post(f'/api/admin/produtos/{produto_id}/imagens/{imagem_id}/excluir')

    assert resposta.status_code == 200
    resposta_json = resposta.get_json()
    assert resposta_json['sucesso'] is True

    with app.app_context():
        produto_atualizado = Produto.query.get(produto_id)
        assert produto_atualizado.imagem_url == 'uploads/segunda.jpg'
        assert ProdutoImagem.query.filter_by(produto_id=produto_id).count() == 1


def test_imagem_disponivel_detecta_assets_e_ignora_caminhos_ausentes(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    with app.app_context():
        assert imagem_disponivel('img/banner_hero1.jpeg')
        assert not imagem_disponivel('uploads/arquivo-que-nao-existe.pdf.gallery.webp')
        assert not imagem_disponivel('../instance/image-originals/banner_hero1.jpg')
