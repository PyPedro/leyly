import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import Pedido, Produto, Usuario


def _criar_app_e_usuario(email='teste@leyly.com', senha='123456'):
    os.environ.pop('MERCADO_PAGO_ACCESS_TOKEN', None)
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        db.drop_all()
        db.create_all()

        usuario = Usuario(nome='Teste', email=email, senha=generate_password_hash(senha), whatsapp='81999999999')
        db.session.add(usuario)
        db.session.flush()

        produto = Produto(
            codigo='REF-TESTE',
            nome='Produto teste',
            preco=100.0,
            etiqueta='TESTE',
            imagem_url='img/teste.jpg',
            estoque_p=10,
            estoque_m=10,
            estoque_g=10,
            estoque_gg=10,
        )
        db.session.add(produto)
        db.session.flush()

        pedido = Pedido(
            usuario_id=usuario.id,
            status='ABERTO',
            itens=json.dumps([
                {
                    'id': produto.id,
                    'nome': produto.nome,
                    'tamanho': 'P',
                    'cor': 'Preto',
                    'preco': 100.0,
                    'quantidade': 4,
                    'imagem': produto.imagem_url,
                }
            ]),
            valor_total=400.0,
            frete_tipo='Excursão',
            endereco='Rua Teste, 123',
            data_atualizacao=datetime.utcnow(),
        )
        db.session.add(pedido)
        nome_usuario = usuario.nome
        whatsapp_usuario = usuario.whatsapp
        db.session.commit()

        return app, nome_usuario, whatsapp_usuario


def test_checkout_abre_whatsapp_com_copia_do_pedido_sem_mercado_pago():
    app, nome, whatsapp = _criar_app_e_usuario()
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.nome_cliente = 'Mana Store - Nome do Pedido'
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login_response.status_code == 200
        assert login_response.get_json()['sucesso'] is True

        with patch('app.routes.requests.post') as mock_post:
            response = client.post('/checkout-infinitepay', json={'frete': 15, 'frete_tipo': 'Excursão'})

        assert response.status_code == 200
        dados = response.get_json()
        assert dados['sucesso'] is True
        url = dados['url_whatsapp']
        assert url.startswith('https://wa.me/558199475717?text=')
        mensagem = parse_qs(urlparse(url).query)['text'][0]
        assert f'Nome: Mana Store - Nome do Pedido' in mensagem
        assert 'WhatsApp: +55 (81) 99999-9999' in mensagem
        assert 'Pedido #1' in mensagem
        assert '# Produto teste - *P* (Preto) - Ref: REF-TESTE' in mensagem
        assert 'Endereço de envio: Rua Teste, 123' in mensagem
        assert 'Quantidade: 4 / Valor: R$ 100,00' in mensagem
        assert 'Subtotal: R$ 400,00' in mensagem
        assert 'Frete estimado (não incluído no total): R$ 10,00' in mensagem
        assert 'Total da compra (produtos): R$ 400,00' in mensagem
        assert 'Valor Final: R$ 410,00' not in mensagem
        assert 'Frete estimado (não incluído no total): R$ 10,00' in mensagem
        assert 'Total da compra (produtos): R$ 400,00' in mensagem
        assert 'Forma de Pagamento:\nPIX' in mensagem
        assert 'Forma de Envio:\nExcursão' in mensagem
        assert 'Motorista ou Excursão:\nNome: Não informado' in mensagem
        assert 'Imprimir Pedido:\nhttp://localhost/admin (localize o pedido #1)' in mensagem
        with app.app_context():
            pedido = Pedido.query.get(1)
            assert pedido.status == 'PAGO'
            assert pedido.frete_tipo == 'Excursão'
            assert pedido.valor_total == 400
            assert pedido.frete_estimado == 10
        mock_post.assert_not_called()


def test_checkout_nao_finaliza_sem_escolher_frete():
    app, nome, whatsapp = _criar_app_e_usuario()
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.frete_tipo = 'Não selecionado'
        db.session.commit()

    with app.test_client() as client:
        client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        resposta = client.post('/checkout-infinitepay', json={'frete': 0, 'frete_tipo': 'Não selecionado'})

    assert resposta.status_code == 400
    assert 'Escolha uma forma de envio' in resposta.get_json()['mensagem']
    with app.app_context():
        assert Pedido.query.one().status == 'ABERTO'


def test_cliente_inclui_observacao_e_escolhe_retirada_em_surubim():
    app, nome, whatsapp = _criar_app_e_usuario()
    observacao = 'Separar as peças por tamanho.'

    with app.test_client() as client:
        login = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login.get_json()['sucesso'] is True
        pagina = client.get('/').get_data(as_text=True)
        assert 'id="observacaoPedido"' in pagina
        assert 'id="imageZoomDialog"' in pagina
        assert 'Retirada em Surubim' in pagina

        salvar_observacao = client.post('/api/carrinho/observacao', json={'observacao': observacao})
        assert salvar_observacao.get_json()['sucesso'] is True
        carrinho = client.get('/api/carrinho').get_json()
        assert carrinho['observacao'] == observacao

        checkout = client.post('/checkout-infinitepay', json={
            'frete': 0,
            'frete_tipo': 'Retirada em Surubim',
            'observacao': observacao,
        })

    assert checkout.get_json()['sucesso'] is True
    mensagem = parse_qs(urlparse(checkout.get_json()['url_whatsapp']).query)['text'][0]
    assert 'Endereço de envio: Retirada em Surubim' in mensagem
    assert f'Observação do cliente: {observacao}' in mensagem
    assert 'Frete estimado (não incluído no total): R$ 0,00' in mensagem
    with app.app_context():
        pedido = Pedido.query.one()
        assert pedido.status == 'PAGO'
        assert pedido.frete_tipo == 'Retirada em Surubim'
        assert pedido.endereco == 'Retirada em Surubim'
        assert pedido.observacao == observacao
        assert pedido.frete_estimado == 0


def test_carrinho_permanece_apos_30_min_logout_login_e_reserva_no_checkout():
    app, nome, whatsapp = _criar_app_e_usuario()
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.data_atualizacao = datetime.utcnow() - timedelta(minutes=31)
        produto = Produto.query.one()
        produto.variantes = json.dumps([{'cor': 'Preto', 'tamanhos': [
            {'nome': 'P', 'estoque': 6, 'preco': 100.0},
        ]}])
        db.session.commit()

    with app.test_client() as client:
        login = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login.get_json()['sucesso'] is True
        client.get('/')

        sacola_expirada = client.get('/api/carrinho').get_json()
        assert sacola_expirada['status'] == 'ABANDONADO'
        assert sacola_expirada['carrinho'][0]['quantidade'] == 4
        with app.app_context():
            assert json.loads(Produto.query.one().variantes)[0]['tamanhos'][0]['estoque'] == 10

        client.get('/logout')
        login_novamente = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login_novamente.get_json()['sucesso'] is True
        client.get('/')
        sacola_restaurada = client.get('/api/carrinho').get_json()
        assert sacola_restaurada['status'] == 'ABANDONADO'
        assert sacola_restaurada['carrinho'][0]['quantidade'] == 4
        with app.app_context():
            assert json.loads(Produto.query.one().variantes)[0]['tamanhos'][0]['estoque'] == 10

        checkout = client.post('/checkout-infinitepay', json={'frete': 0, 'frete_tipo': 'Excursão'})

    assert checkout.get_json()['sucesso'] is True
    with app.app_context():
        assert Pedido.query.one().status == 'PAGO'
        assert json.loads(Produto.query.one().variantes)[0]['tamanhos'][0]['estoque'] == 6


def test_checkout_de_carrinho_abandonado_recusa_estoque_indisponivel():
    app, nome, whatsapp = _criar_app_e_usuario()
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.status = 'ABANDONADO'
        produto = Produto.query.one()
        produto.variantes = json.dumps([{'cor': 'Preto', 'tamanhos': [
            {'nome': 'P', 'estoque': 3, 'preco': 100.0},
        ]}])
        db.session.commit()

    with app.test_client() as client:
        client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        resposta = client.post('/checkout-infinitepay', json={'frete': 0, 'frete_tipo': 'Excursão'})

    assert resposta.status_code == 409
    assert resposta.get_json()['sucesso'] is False
    assert 'Estoque insuficiente' in resposta.get_json()['mensagem']
    with app.app_context():
        assert Pedido.query.one().status == 'ABANDONADO'
        assert json.loads(Produto.query.one().variantes)[0]['tamanhos'][0]['estoque'] == 3


def test_admin_edita_pedido_e_cancela_devolvendo_estoque():
    app, _, _ = _criar_app_e_usuario()
    with app.app_context():
        pedido = Pedido.query.one()
        produto = Produto.query.one()
        pedido.frete_estimado = 15
        produto.imagem_url = 'img/logo.png'
        produto.variantes = json.dumps([{'cor': 'Preto', 'tamanhos': [
            {'nome': 'P', 'estoque': 6, 'preco': 100.0},
        ]}])
        pedido_id = pedido.id
        produto_id = produto.id
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        pagina_admin = client.get('/admin').get_data(as_text=True)
        assert 'id="editar-pedido-nome-cliente"' in pagina_admin
        assert 'id="editar-pedido-observacao"' in pagina_admin
        assert 'id="imprimir-pedidos-selecionados"' in pagina_admin
        assert 'id="detalhe-whatsapp-pedido"' in pagina_admin
        assert 'id="batchPrintArea"' in pagina_admin
        assert 'order-card-number' in pagina_admin
        assert 'order-card-contact' in pagina_admin
        assert 'alternarDetalhesPedido(this)' in pagina_admin
        assert 'print-product-image' in pagina_admin
        pedidos_admin = client.get('/api/admin/pedidos').get_json()
        assert pedidos_admin[0]['itens'][0]['imagem_url'].endswith('/static/img/logo.png')

        estoque_insuficiente = client.post('/api/admin/pedidos/editar', json={
            'id': pedido_id,
            'quantidades': [20],
        })
        assert estoque_insuficiente.status_code == 409
        with app.app_context():
            assert json.loads(Pedido.query.one().itens)[0]['quantidade'] == 4
            assert json.loads(Produto.query.one().variantes)[0]['tamanhos'][0]['estoque'] == 6

        edicao = client.post('/api/admin/pedidos/editar', json={
            'id': pedido_id,
            'nome_cliente': 'Mana Store - Filial Centro',
            'observacao': 'Separar em embalagem presente.',
            'endereco': 'Rua Nova, 25 - Centro, Recife/PE - CEP: 50000000',
            'frete_tipo': 'Correios',
            'quantidades': [5],
        })
        assert edicao.status_code == 200
        assert edicao.get_json()['total'] == 500
        with app.app_context():
            pedido_atualizado = Pedido.query.one()
            produto_atualizado = db.session.get(Produto, produto_id)
            assert pedido_atualizado.nome_cliente == 'Mana Store - Filial Centro'
            assert pedido_atualizado.observacao == 'Separar em embalagem presente.'
            assert pedido_atualizado.endereco == 'Rua Nova, 25 - Centro, Recife/PE - CEP: 50000000'
            assert pedido_atualizado.frete_tipo == 'Correios'
            assert pedido_atualizado.frete_estimado == 15
            assert json.loads(pedido_atualizado.itens)[0]['quantidade'] == 5
            assert json.loads(produto_atualizado.variantes)[0]['tamanhos'][0]['estoque'] == 5

        pedido_admin = client.get('/api/admin/pedidos').get_json()[0]
        assert pedido_admin['cliente'] == 'Mana Store - Filial Centro'
        assert pedido_admin['observacao'] == 'Separar em embalagem presente.'

        cancelamento = client.post('/api/admin/pedidos/cancelar', json={'id': pedido_id})
        assert cancelamento.status_code == 200
        assert cancelamento.get_json()['sucesso'] is True
        cancelamento_duplicado = client.post('/api/admin/pedidos/cancelar', json={'id': pedido_id})
        assert cancelamento_duplicado.status_code == 409
        reativacao = client.post('/api/admin/pedidos/atualizar-status', json={
            'id': pedido_id,
            'status': 'SEPARACAO',
        })
        assert reativacao.status_code == 409

    with app.app_context():
        assert Pedido.query.one().status == 'CANCELADO'
        assert json.loads(db.session.get(Produto, produto_id).variantes)[0]['tamanhos'][0]['estoque'] == 10


def test_admin_nao_cancela_pedido_enviado():
    app, _, _ = _criar_app_e_usuario()
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.status = 'ENVIADO'
        pedido_id = pedido.id
        produto = Produto.query.one()
        produto.variantes = json.dumps([{'cor': 'Preto', 'tamanhos': [
            {'nome': 'P', 'estoque': 6, 'preco': 100.0},
        ]}])
        produto_id = produto.id
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        resposta = client.post('/api/admin/pedidos/cancelar', json={'id': pedido_id})

    assert resposta.status_code == 409
    with app.app_context():
        assert db.session.get(Pedido, pedido_id).status == 'ENVIADO'
        assert json.loads(db.session.get(Produto, produto_id).variantes)[0]['tamanhos'][0]['estoque'] == 6


def test_admin_nao_confirma_pedido_abaixo_do_minimo():
    app, _, _ = _criar_app_e_usuario()
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.itens = json.dumps([{**json.loads(pedido.itens)[0], 'quantidade': 3}])
        pedido.valor_total = 300
        pedido_id = pedido.id
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        resposta = client.post('/api/admin/pedidos/atualizar-status', json={
            'id': pedido_id,
            'status': 'PAGO',
        })

    assert resposta.status_code == 409
    assert 'mínimo' in resposta.get_json()['mensagem']
    with app.app_context():
        assert db.session.get(Pedido, pedido_id).status == 'ABERTO'


def test_admin_nao_edita_pedido_confirmado_abaixo_do_minimo():
    app, _, _ = _criar_app_e_usuario()
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.status = 'PAGO'
        produto = Produto.query.one()
        produto.variantes = json.dumps([{'cor': 'Preto', 'tamanhos': [
            {'nome': 'P', 'estoque': 6, 'preco': 100.0},
        ]}])
        pedido_id = pedido.id
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        resposta = client.post('/api/admin/pedidos/editar', json={
            'id': pedido_id,
            'quantidades': [3],
        })

    assert resposta.status_code == 409
    assert 'mínimo' in resposta.get_json()['mensagem']
    with app.app_context():
        assert json.loads(db.session.get(Pedido, pedido_id).itens)[0]['quantidade'] == 4
        assert json.loads(Produto.query.one().variantes)[0]['tamanhos'][0]['estoque'] == 6


def test_checkout_inclui_endereco_do_cep_calculado_antes_do_pedido():
    app, nome, whatsapp = _criar_app_e_usuario()
    with app.app_context():
        Pedido.query.delete()
        produto = Produto.query.one()
        produto.variantes = json.dumps([{'cor': 'Preto', 'tamanhos': [
            {'nome': 'P', 'estoque': 10, 'preco': 100},
        ]}])
        produto_id = produto.id
        nome_produto = produto.nome
        db.session.commit()

    with app.test_client() as client:
        login = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login.get_json()['sucesso'] is True

        respostas_cep = [
            SimpleNamespace(status_code=200, json=lambda: {'uf': 'PE', 'localidade': 'Origem'}),
            SimpleNamespace(status_code=200, json=lambda: {
                'logradouro': 'Rua Direita', 'bairro': 'Centro', 'localidade': 'São Paulo', 'uf': 'SP',
            }),
        ]
        with patch('app.routes.requests.get', side_effect=respostas_cep):
            resposta_frete = client.post('/calcular-frete', json={
                'cep': '01001-000',
                'carrinho': [{'quantidade': 4}],
            })

        dados_frete = resposta_frete.get_json()
        assert dados_frete['sucesso'] is True
        assert dados_frete['endereco_destino'] == 'Rua Direita, Centro - São Paulo/SP - CEP: 01001000'

        sincronizacao = client.post('/api/carrinho/sync', json={'carrinho': [{
            'id': produto_id,
            'nome': nome_produto,
            'cor': 'Preto',
            'tamanho': 'P',
            'quantidade': 4,
        }]})
        assert sincronizacao.get_json()['sucesso'] is True

        resposta_checkout = client.post('/checkout-infinitepay', json={'frete': 15, 'frete_tipo': 'Excursão'})

    dados_checkout = resposta_checkout.get_json()
    assert dados_checkout['sucesso'] is True
    mensagem = parse_qs(urlparse(dados_checkout['url_whatsapp']).query)['text'][0]
    assert f'Nome: {nome}' in mensagem
    assert 'WhatsApp: +55 (81) 99999-9999' in mensagem
    assert 'Endereço de envio: Rua Direita, Centro - São Paulo/SP - CEP: 01001000' in mensagem
    assert 'De: MODA CENTER SANTA CRUZ / Para: São Paulo-SP' in mensagem


def test_cadastro_login_nome_whatsapp_e_carrossel_principal():
    app, _, _ = _criar_app_e_usuario()

    with app.test_client() as client:
        cadastro = client.post('/api/cadastro', json={
            'nome': '  Maria da Silva  ',
            'whatsapp': '+55 (81) 98888-7777',
        })
        assert cadastro.get_json()['sucesso'] is True

        with client.session_transaction() as sessao:
            sessao.clear()

        login = client.post('/api/login', json={
            'nome': 'maria da silva',
            'whatsapp': '5581988887777',
        })
        assert login.get_json()['sucesso'] is True

        pagina = client.get('/').get_data(as_text=True)
        assert pagina.count('class="hero-slide"') + pagina.count('class="hero-slide is-active"') == 3
        assert 'id="loginNome"' in pagina
        assert 'id="loginWhatsapp"' in pagina
        assert 'id="loginEmail"' not in pagina
        assert 'id="cadEmail"' not in pagina


def test_busca_catalogo_encontra_produto_fora_das_promocoes():
    app, _, _ = _criar_app_e_usuario()

    with app.test_client() as client:
        resposta = client.get('/api/produtos/buscar?q=REF-TESTE')

    assert resposta.status_code == 200
    produtos = resposta.get_json()
    assert len(produtos) == 1
    assert produtos[0]['codigo'] == 'REF-TESTE'
    assert produtos[0]['nome'] == 'Produto teste'
