import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import Pedido, Produto, Usuario, Visita


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


def test_checkout_cria_preferencia_mercado_pago_e_aguarda_confirmacao():
    app, nome, whatsapp = _criar_app_e_usuario()
    app.config['MERCADO_PAGO_ACCESS_TOKEN'] = 'TEST-TOKEN'
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.nome_cliente = 'Mana Store - Nome do Pedido'
        db.session.commit()

    with app.test_client() as client:
        login_response = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login_response.status_code == 200
        assert login_response.get_json()['sucesso'] is True

        with patch('app.routes.requests.post') as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {
                'init_point': 'https://www.mercadopago.com.br/checkout/live',
                'sandbox_init_point': 'https://sandbox.mercadopago.com.br/checkout/test',
            }
            response = client.post('/checkout-mercadopago', json={'frete': 15, 'frete_tipo': 'Excursão'})

        assert response.status_code == 200
        dados = response.get_json()
        assert dados['sucesso'] is True
        assert dados['url_pagamento'] == 'https://sandbox.mercadopago.com.br/checkout/test'
        payload_mp = mock_post.call_args.kwargs['json']
        assert payload_mp['external_reference'] == '1'
        assert payload_mp['items'][-1] == {
            'title': 'Frete - Excursão',
            'quantity': 1,
            'currency_id': 'BRL',
            'unit_price': 10.0,
        }
        assert payload_mp['payer'] == {'name': 'Teste', 'email': 'teste@leyly.com'}
        assert payload_mp['notification_url'] == 'http://localhost/api/mercadopago/webhook'
        with app.app_context():
            pedido = Pedido.query.get(1)
            assert pedido.status == 'PAGAMENTO'
            assert pedido.frete_tipo == 'Excursão'
            assert pedido.valor_total == 400
            assert pedido.frete_estimado == 10


def test_checkout_sem_token_mercado_pago_nao_altera_pedido():
    app, nome, whatsapp = _criar_app_e_usuario()

    with app.test_client() as client:
        login = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login.get_json()['sucesso'] is True
        resposta = client.post('/checkout-mercadopago', json={
            'frete': 10,
            'frete_tipo': 'Excursão',
        })

    assert resposta.status_code == 503
    assert 'MERCADO_PAGO_ACCESS_TOKEN' in resposta.get_json()['mensagem']
    with app.app_context():
        assert Pedido.query.one().status == 'ABERTO'


def test_checkout_com_token_de_producao_usa_init_point():
    app, nome, whatsapp = _criar_app_e_usuario()
    app.config['MERCADO_PAGO_ACCESS_TOKEN'] = 'APP_USR-token-producao'

    with app.test_client() as client:
        login = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login.get_json()['sucesso'] is True
        with patch('app.routes.requests.post') as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {
                'init_point': 'https://www.mercadopago.com.br/checkout/live',
                'sandbox_init_point': 'https://sandbox.mercadopago.com/checkout/test',
            }
            resposta = client.post('/checkout-mercadopago', json={
                'frete': 0,
                'frete_tipo': 'Retirada em Surubim',
            })

    assert resposta.get_json()['url_pagamento'] == 'https://www.mercadopago.com.br/checkout/live'
    assert mock_post.call_args.kwargs['headers']['Authorization'] == 'Bearer APP_USR-token-producao'


def test_webhook_confirma_pagamento_aprovado_validado_no_mercado_pago():
    app, _, _ = _criar_app_e_usuario()
    app.config['MERCADO_PAGO_ACCESS_TOKEN'] = 'APP_USR-token-producao'
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.status = 'PAGAMENTO'
        pedido.frete_estimado = 10
        db.session.commit()

    with app.test_client() as client:
        with patch('app.routes.requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                'status': 'approved',
                'currency_id': 'BRL',
                'transaction_amount': 410.0,
                'external_reference': '1',
            }
            resposta = client.post('/api/mercadopago/webhook', json={'data': {'id': 'payment-123'}})

    assert resposta.status_code == 200
    mock_get.assert_called_once_with(
        'https://api.mercadopago.com/v1/payments/payment-123',
        headers={'Authorization': 'Bearer APP_USR-token-producao'},
        timeout=10,
    )
    with app.app_context():
        pedido = Pedido.query.one()
        assert pedido.status == 'PAGO'
        assert pedido.numero_separacao == 1


def test_webhook_nao_confirma_pagamento_com_valor_divergente():
    app, _, _ = _criar_app_e_usuario()
    app.config['MERCADO_PAGO_ACCESS_TOKEN'] = 'APP_USR-token-producao'
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.status = 'PAGAMENTO'
        pedido.frete_estimado = 10
        db.session.commit()

    with app.test_client() as client:
        with patch('app.routes.requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                'status': 'approved',
                'currency_id': 'BRL',
                'transaction_amount': 400.0,
                'external_reference': '1',
            }
            resposta = client.post('/api/mercadopago/webhook', json={'data': {'id': 'payment-123'}})

    assert resposta.status_code == 200
    with app.app_context():
        assert Pedido.query.one().status == 'PAGAMENTO'


def test_checkout_excursao_usa_carrinho_sincronizado_antes_de_validar_minimo():
    app, nome, whatsapp = _criar_app_e_usuario()
    app.config['MERCADO_PAGO_ACCESS_TOKEN'] = 'TEST-TOKEN'
    with app.app_context():
        pedido = Pedido.query.one()
        itens = json.loads(pedido.itens)
        itens[0]['quantidade'] = 3
        pedido.itens = json.dumps(itens)
        Produto.query.one().variantes = json.dumps([{'cor': 'Preto', 'tamanhos': [
            {'nome': 'P', 'estoque': 10, 'preco': 100.0},
        ]}])
        db.session.commit()

    with app.test_client() as client:
        login = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login.get_json()['sucesso'] is True

        carrinho = client.get('/api/carrinho').get_json()['carrinho']
        carrinho[0]['quantidade'] = 4
        sincronizacao = client.post('/api/carrinho/sync', json={
            'carrinho': carrinho,
            'frete': 10,
            'frete_tipo': 'Excursão',
        })
        with patch('app.routes.requests.post') as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {'sandbox_init_point': 'https://sandbox.mercadopago.com/checkout/test'}
            checkout = client.post('/checkout-mercadopago', json={
                'frete': 10,
                'frete_tipo': 'Excursão',
            })

    assert sincronizacao.get_json()['sucesso'] is True, sincronizacao.get_json()
    assert checkout.get_json()['sucesso'] is True
    assert checkout.get_json()['url_pagamento'] == 'https://sandbox.mercadopago.com/checkout/test'
    assert mock_post.call_args.kwargs['json']['items'][0]['quantity'] == 4


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


def test_compras_pausadas_bloqueiam_reserva_e_checkout():
    app, nome, whatsapp = _criar_app_e_usuario()
    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        pausa = client.post('/api/admin/compras', json={'ativas': False})
        assert pausa.get_json() == {'sucesso': True, 'ativas': False}

        login = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login.get_json()['sucesso'] is True
        reserva = client.post('/api/carrinho/sync', json={'carrinho': []})
        checkout = client.post('/checkout-infinitepay', json={'frete_tipo': 'Excursão'})
        pagina = client.get('/').get_data(as_text=True)
        reabertura = client.post('/api/admin/compras', json={'ativas': True})

    assert reserva.status_code == 409
    assert checkout.status_code == 409
    assert reserva.get_json()['sucesso'] is False
    assert checkout.get_json()['sucesso'] is False
    assert 'CATÁLOGO inativo temporariamente' in pagina
    assert '<section id="inicio" class="hero-section"' in pagina
    assert '<section class="category-palette"' not in pagina
    assert '<main id="loja"' not in pagina
    assert 'ALTA RENTABILIDADE PARA SEU NEGÓCIO' not in pagina
    assert reabertura.get_json() == {'sucesso': True, 'ativas': True}
    with app.app_context():
        assert Pedido.query.one().status == 'ABERTO'


def test_cliente_inclui_observacao_e_escolhe_retirada_em_surubim():
    app, nome, whatsapp = _criar_app_e_usuario()
    app.config['MERCADO_PAGO_ACCESS_TOKEN'] = 'APP_USR-token'
    observacao = 'Separar as peças por tamanho.'

    with app.test_client() as client:
        login = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login.get_json()['sucesso'] is True
        pagina = client.get('/').get_data(as_text=True)
        assert 'id="observacaoPedido"' in pagina
        assert 'id="imageZoomDialog"' in pagina
        assert 'Retirada em Surubim' in pagina
        assert pagina.index('data-tipo="Retirada em Surubim"') < pagina.index('data-tipo="Excursão"')
        assert 'Taxa fixa de R$ 10,00 somada ao total do pedido' in pagina

        salvar_observacao = client.post('/api/carrinho/observacao', json={'observacao': observacao})
        assert salvar_observacao.get_json()['sucesso'] is True
        carrinho = client.get('/api/carrinho').get_json()
        assert carrinho['observacao'] == observacao

        with patch('app.routes.requests.post') as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {'init_point': 'https://www.mercadopago.com.br/checkout/live'}
            checkout = client.post('/checkout-mercadopago', json={
                'frete': 0,
                'frete_tipo': 'Retirada em Surubim',
                'observacao': observacao,
            })

    assert checkout.get_json()['sucesso'] is True
    assert checkout.get_json()['url_pagamento'] == 'https://www.mercadopago.com.br/checkout/live'
    with app.app_context():
        pedido = Pedido.query.one()
        assert pedido.status == 'PAGAMENTO'
        assert pedido.frete_tipo == 'Retirada em Surubim'
        assert pedido.endereco == 'Retirada em Surubim'
        assert pedido.observacao == observacao
        assert pedido.frete_estimado == 0


def test_carrinho_permanece_apos_30_min_logout_login_e_reserva_no_checkout():
    app, nome, whatsapp = _criar_app_e_usuario()
    app.config['MERCADO_PAGO_ACCESS_TOKEN'] = 'TEST-TOKEN'
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

        with patch('app.routes.requests.post') as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {'sandbox_init_point': 'https://sandbox.mercadopago.com/checkout/test'}
            checkout = client.post('/checkout-mercadopago', json={'frete': 0, 'frete_tipo': 'Excursão'})

    assert checkout.get_json()['sucesso'] is True
    assert checkout.get_json()['url_pagamento'] == 'https://sandbox.mercadopago.com/checkout/test'
    with app.app_context():
        assert Pedido.query.one().status == 'PAGAMENTO'
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
        assert 'id="buscar-pedido"' in pagina_admin
        assert 'filtrarPedidosPorNumero(this.value)' in pagina_admin
        assert 'id="editar-pedido-nome-cliente"' in pagina_admin
        assert 'id="editar-pedido-observacao"' in pagina_admin
        assert 'id="editar-pedido-produto"' in pagina_admin
        assert 'id="editar-pedido-cor"' in pagina_admin
        assert 'id="editar-pedido-tamanho"' in pagina_admin
        assert 'adicionarItemEdicaoPedido()' in pagina_admin
        assert 'removerItemEdicaoPedido(indice)' in pagina_admin
        assert 'id="imprimir-pedidos-selecionados"' in pagina_admin
        assert 'id="detalhe-whatsapp-pedido"' in pagina_admin
        assert 'id="batchPrintArea"' in pagina_admin
        assert 'order-card-number' in pagina_admin
        assert 'order-card-contact' in pagina_admin
        assert 'alternarDetalhesPedido(this)' in pagina_admin
        assert 'print-product-image' in pagina_admin
        assert 'Quantidade total de itens:' in pagina_admin
        assert '@page { margin: 18mm 12mm 12mm; }' in pagina_admin
        assert '.print-order tr { break-inside: avoid-page; page-break-inside: avoid; }' in pagina_admin
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


def test_api_admin_pedidos_numera_todos_em_sequencia(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app, _, _ = _criar_app_e_usuario()
    with app.app_context():
        pedido_existente = Pedido.query.one()
        usuario_id = pedido_existente.usuario_id
        pedido_existente.id = 20
        pedido_existente.status = 'PAGO'
        db.session.flush()
        db.session.add(Pedido(id=3, usuario_id=usuario_id, status='PAGO'))
        db.session.add(Pedido(id=11, usuario_id=usuario_id, status='PAGAMENTO'))
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        pedidos = client.get('/api/admin/pedidos').get_json()

    assert [pedido['id'] for pedido in pedidos] == [3, 11, 20]
    assert [pedido['numero_separacao'] for pedido in pedidos] == [1, 2, 3]


def test_admin_nao_marca_pedido_pago_sem_confirmacao_do_mercado_pago():
    app, _, _ = _criar_app_e_usuario()
    with app.app_context():
        pedido_id = Pedido.query.one().id

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        resposta = client.post('/api/admin/pedidos/atualizar-status', json={
            'id': pedido_id,
            'status': 'PAGO',
        })

    assert resposta.status_code == 409
    assert 'Mercado Pago' in resposta.get_json()['mensagem']
    with app.app_context():
        assert db.session.get(Pedido, pedido_id).status == 'ABERTO'


def test_admin_nao_avanca_pedido_sem_confirmacao_do_pagamento():
    app, _, _ = _criar_app_e_usuario()
    with app.app_context():
        pedido_id = Pedido.query.one().id

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        resposta = client.post('/api/admin/pedidos/atualizar-status', json={
            'id': pedido_id,
            'status': 'SEPARACAO',
        })

    assert resposta.status_code == 409
    assert 'confirmação do pagamento' in resposta.get_json()['mensagem']
    with app.app_context():
        assert db.session.get(Pedido, pedido_id).status == 'ABERTO'


def test_dashboard_e_relatorios_filtram_dados_pelo_periodo():
    app, _, _ = _criar_app_e_usuario()
    hoje = datetime.utcnow()
    inicio = (hoje - timedelta(days=30)).date()
    fim = hoje.date()
    with app.app_context():
        pedido_pago = Pedido.query.one()
        produto = Produto.query.one()
        pedido_pago.status = 'PAGO'
        pedido_pago.data_atualizacao = hoje - timedelta(days=10)
        pedido_pago.valor_total = 400
        pedido_historico = Pedido(
            usuario_id=pedido_pago.usuario_id,
            status='PAGO',
            itens=json.dumps([{'id': produto.id, 'nome': produto.nome, 'preco': 100, 'quantidade': 2, 'tamanho': 'P'}]),
            valor_total=200,
            data_atualizacao=hoje - timedelta(days=45),
        )
        pedido_enviado = Pedido(
            usuario_id=pedido_pago.usuario_id,
            status='ENVIADO',
            itens=json.dumps([{'id': produto.id, 'nome': produto.nome, 'preco': 250, 'quantidade': 1, 'tamanho': 'P'}]),
            valor_total=250,
            data_atualizacao=hoje - timedelta(days=2),
        )
        pedido_aberto = Pedido(
            usuario_id=pedido_pago.usuario_id,
            status='PAGAMENTO',
            itens=json.dumps([{'id': produto.id, 'nome': produto.nome, 'preco': 100, 'quantidade': 4, 'tamanho': 'P'}]),
            valor_total=400,
            data_atualizacao=hoje,
        )
        pedido_abandonado = Pedido(
            usuario_id=pedido_pago.usuario_id,
            status='ABANDONADO',
            itens=json.dumps([{'id': produto.id, 'nome': produto.nome, 'preco': 100, 'quantidade': 1, 'tamanho': 'P'}]),
            valor_total=75,
            data_atualizacao=hoje - timedelta(days=5),
        )
        db.session.add_all([
            pedido_historico,
            pedido_enviado,
            pedido_aberto,
            pedido_abandonado,
            Visita(data_visita=hoje - timedelta(days=3)),
            Visita(data_visita=hoje - timedelta(days=45)),
        ])
        db.session.commit()

    query = f'?inicio={inicio.isoformat()}&fim={fim.isoformat()}'
    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        dashboard = client.get(f'/api/admin/dashboard{query}').get_json()
        relatorios = client.get(f'/api/admin/relatorios{query}').get_json()
        marketing = client.get(f'/api/admin/marketing{query}').get_json()

    assert dashboard['kpis']['faturamento'] == 650
    assert dashboard['kpis']['pecas_vendidas'] == 5
    assert dashboard['kpis']['valor_perdido'] == 75
    assert dashboard['atuais']['pedidos_abertos'] == 1
    assert sum(relatorios['acessos']) == 1
    assert sum(relatorios['vendas']) == 2
    assert marketing['funil'] == {'visitas': 1, 'iniciados': 4, 'pagos': 2}


def test_filtro_periodo_rejeita_datas_invertidas():
    app, _, _ = _criar_app_e_usuario()
    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        resposta = client.get('/api/admin/dashboard?inicio=2026-10-20&fim=2026-10-01')

    assert resposta.status_code == 400
    assert 'posterior' in resposta.get_json()['mensagem']


def test_superfrete_emite_etiqueta_e_salva_envio_para_reimpressao():
    app, _, _ = _criar_app_e_usuario()
    app.config['SUPERFRETE_TOKEN'] = 'token-superfrete-teste'
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.status = 'SEPARACAO'
        pedido.endereco = 'Rua de Teste, Bairro Centro - Recife/PE - CEP: 50000-000'
        pedido.frete_tipo = 'Correios'
        pedido_id = pedido.id
        db.session.commit()

    enderecos = [{
        'name': 'Loja Leyly', 'postal_code': '55750000', 'address': 'Rua da Loja',
        'number': '10', 'district': 'Centro', 'city': 'Surubim', 'state_abbr': 'PE',
        'is_primary': True,
    }]
    via_cep = {'logradouro': 'Rua de Teste', 'bairro': 'Centro', 'localidade': 'Recife', 'uf': 'PE'}
    cotacoes = [{'id': 1, 'name': 'PAC', 'price': 12.5}, {'id': 2, 'name': 'SEDEX', 'price': 20.0}]
    carrinho = {'id': 'sf-order-123'}
    checkout = {'success': True, 'purchase': {'orders': [
        {'id': 'sf-order-123', 'tracking': 'BR123456789', 'print': {'url': 'https://superfrete.test/label.pdf'}},
    ]}}

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        with patch('app.routes.requests.get') as mock_get, patch('app.routes.requests.post') as mock_post:
            mock_get.side_effect = [
                SimpleNamespace(ok=True, json=lambda: via_cep),
                SimpleNamespace(ok=True, json=lambda: enderecos),
            ]
            mock_post.side_effect = [
                SimpleNamespace(ok=True, status_code=200, json=lambda: cotacoes),
                SimpleNamespace(ok=True, status_code=201, json=lambda: carrinho),
                SimpleNamespace(ok=True, status_code=200, json=lambda: checkout),
            ]
            resposta = client.post(f'/api/admin/gerar-etiqueta/{pedido_id}')

    assert resposta.status_code == 200
    assert resposta.get_json()['url_etiqueta'] == 'https://superfrete.test/label.pdf'
    assert mock_post.call_args_list[0].kwargs['json']['services'] == '1,2'
    assert mock_post.call_args_list[1].kwargs['json']['service'] == 1
    assert mock_post.call_args_list[2].kwargs['json'] == {'orders': ['sf-order-123']}
    assert all(call.kwargs['headers']['Authorization'] == 'Bearer token-superfrete-teste' for call in mock_post.call_args_list)
    with app.app_context():
        pedido = db.session.get(Pedido, pedido_id)
        assert pedido.superfrete_order_id == 'sf-order-123'
        assert pedido.superfrete_tracking == 'BR123456789'


def test_superfrete_reimprime_etiqueta_sem_comprar_novamente():
    app, _, _ = _criar_app_e_usuario()
    app.config['SUPERFRETE_TOKEN'] = 'token-superfrete-teste'
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.status = 'ENVIADO'
        pedido.superfrete_order_id = 'sf-order-existing'
        pedido_id = pedido.id
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        with patch('app.routes.requests.get') as mock_get, patch('app.routes.requests.post') as mock_post:
            mock_get.return_value.ok = True
            mock_get.return_value.json.return_value = {'id': 'sf-order-existing', 'status': 'released'}
            mock_post.return_value.ok = True
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {'url': 'https://superfrete.test/reprint.pdf'}
            resposta = client.post(f'/api/admin/gerar-etiqueta/{pedido_id}')

    assert resposta.status_code == 200
    assert resposta.get_json()['reimpressao'] is True
    assert resposta.get_json()['url_etiqueta'] == 'https://superfrete.test/reprint.pdf'
    mock_post.assert_called_once_with(
        'https://api.superfrete.com/api/v0/tag/print',
        json={'orders': ['sf-order-existing']},
        headers=mock_post.call_args.kwargs['headers'],
        timeout=15,
    )


def test_superfrete_reaproveita_envio_pendente_ao_tentar_novamente():
    app, _, _ = _criar_app_e_usuario()
    app.config['SUPERFRETE_TOKEN'] = 'token-superfrete-teste'
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.status = 'SEPARACAO'
        pedido.superfrete_order_id = 'sf-order-pending'
        pedido_id = pedido.id
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        with patch('app.routes.requests.get') as mock_get, patch('app.routes.requests.post') as mock_post:
            mock_get.return_value.ok = True
            mock_get.return_value.json.return_value = {'id': 'sf-order-pending', 'status': 'pending'}
            mock_post.return_value.ok = True
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                'success': True,
                'purchase': {'orders': [
                    {'id': 'sf-order-pending', 'print': {'url': 'https://superfrete.test/pending.pdf'}},
                ]},
            }
            resposta = client.post(f'/api/admin/gerar-etiqueta/{pedido_id}')

    assert resposta.status_code == 200
    assert resposta.get_json()['url_etiqueta'] == 'https://superfrete.test/pending.pdf'
    mock_post.assert_called_once_with(
        'https://api.superfrete.com/api/v0/checkout',
        json={'orders': ['sf-order-pending']},
        headers=mock_post.call_args.kwargs['headers'],
        timeout=20,
    )


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


def test_admin_exclui_pedido_concluido_sem_devolver_estoque():
    app, _, _ = _criar_app_e_usuario()
    with app.app_context():
        pedido = Pedido.query.one()
        pedido.status = 'CONCLUIDO'
        produto = Produto.query.one()
        produto.variantes = json.dumps([{'cor': 'Preto', 'tamanhos': [
            {'nome': 'P', 'estoque': 6, 'preco': 100.0},
        ]}])
        pedido_id = pedido.id
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        pagina_admin = client.get('/admin').get_data(as_text=True)
        resposta = client.post('/api/admin/pedidos/excluir', json={'id': pedido_id})

    assert resposta.status_code == 200
    assert resposta.get_json()['sucesso'] is True
    assert 'detalhe-excluir' in pagina_admin
    with app.app_context():
        assert db.session.get(Pedido, pedido_id) is None
        assert json.loads(Produto.query.one().variantes)[0]['tamanhos'][0]['estoque'] == 6


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


def test_admin_adiciona_item_ao_pedido_e_reserva_estoque():
    app, _, _ = _criar_app_e_usuario()
    with app.app_context():
        pedido = Pedido.query.one()
        produto = Produto.query.one()
        produto.variantes = json.dumps([{'cor': 'Preto', 'tamanhos': [
            {'nome': 'P', 'estoque': 6, 'preco': 100.0},
            {'nome': 'M', 'estoque': 3, 'preco': 50.0},
        ]}])
        pedido_id = pedido.id
        produto_id = produto.id
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        resposta = client.post('/api/admin/pedidos/editar', json={
            'id': pedido_id,
            'itens': [
                {'id': produto_id, 'cor': 'Preto', 'tamanho': 'P', 'quantidade': 4},
                {'id': produto_id, 'cor': 'Preto', 'tamanho': 'M', 'quantidade': 2},
            ],
        })

    assert resposta.status_code == 200
    assert resposta.get_json()['total'] == 500
    with app.app_context():
        pedido = db.session.get(Pedido, pedido_id)
        tamanhos = json.loads(db.session.get(Produto, produto_id).variantes)[0]['tamanhos']
        assert [(item['tamanho'], item['quantidade']) for item in json.loads(pedido.itens)] == [('P', 4), ('M', 2)]
        assert [tamanho['estoque'] for tamanho in tamanhos] == [6, 1]


def test_admin_remove_item_e_reduz_quantidade_devolve_estoque():
    app, _, _ = _criar_app_e_usuario()
    with app.app_context():
        pedido = Pedido.query.one()
        produto = Produto.query.one()
        produto.variantes = json.dumps([{'cor': 'Preto', 'tamanhos': [
            {'nome': 'P', 'estoque': 6, 'preco': 100.0},
            {'nome': 'M', 'estoque': 3, 'preco': 50.0},
        ]}])
        pedido.itens = json.dumps([
            {'id': produto.id, 'nome': produto.nome, 'cor': 'Preto', 'tamanho': 'P', 'preco': 100.0, 'quantidade': 4},
            {'id': produto.id, 'nome': produto.nome, 'cor': 'Preto', 'tamanho': 'M', 'preco': 50.0, 'quantidade': 2},
        ])
        pedido.valor_total = 500
        pedido_id = pedido.id
        produto_id = produto.id
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        resposta = client.post('/api/admin/pedidos/editar', json={
            'id': pedido_id,
            'itens': [{'id': produto_id, 'cor': 'Preto', 'tamanho': 'P', 'quantidade': 2}],
        })

    assert resposta.status_code == 200
    assert resposta.get_json()['total'] == 200
    with app.app_context():
        pedido = db.session.get(Pedido, pedido_id)
        tamanhos = json.loads(db.session.get(Produto, produto_id).variantes)[0]['tamanhos']
        assert [(item['tamanho'], item['quantidade']) for item in json.loads(pedido.itens)] == [('P', 2)]
        assert [tamanho['estoque'] for tamanho in tamanhos] == [8, 5]


def test_admin_rejeita_adicao_sem_estoque_sem_alterar_pedido_ou_estoque():
    app, _, _ = _criar_app_e_usuario()
    with app.app_context():
        pedido = Pedido.query.one()
        produto = Produto.query.one()
        produto.variantes = json.dumps([{'cor': 'Preto', 'tamanhos': [
            {'nome': 'P', 'estoque': 6, 'preco': 100.0},
            {'nome': 'M', 'estoque': 3, 'preco': 50.0},
        ]}])
        pedido_id = pedido.id
        produto_id = produto.id
        itens_antes = pedido.itens
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sessao:
            sessao['admin_logado'] = True
        resposta = client.post('/api/admin/pedidos/editar', json={
            'id': pedido_id,
            'itens': [
                {'id': produto_id, 'cor': 'Preto', 'tamanho': 'P', 'quantidade': 4},
                {'id': produto_id, 'cor': 'Preto', 'tamanho': 'M', 'quantidade': 4},
            ],
        })

    assert resposta.status_code == 409
    assert 'Estoque insuficiente' in resposta.get_json()['mensagem']
    with app.app_context():
        assert db.session.get(Pedido, pedido_id).itens == itens_antes
        tamanhos = json.loads(db.session.get(Produto, produto_id).variantes)[0]['tamanhos']
        assert [tamanho['estoque'] for tamanho in tamanhos] == [6, 3]


def test_checkout_inclui_endereco_do_cep_calculado_antes_do_pedido():
    app, nome, whatsapp = _criar_app_e_usuario()
    app.config['MERCADO_PAGO_ACCESS_TOKEN'] = 'TEST-TOKEN'
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

        with patch('app.routes.requests.post') as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {'sandbox_init_point': 'https://sandbox.mercadopago.com/checkout/test'}
            resposta_checkout = client.post('/checkout-mercadopago', json={'frete': 15, 'frete_tipo': 'Excursão'})

    dados_checkout = resposta_checkout.get_json()
    assert dados_checkout['sucesso'] is True
    assert dados_checkout['url_pagamento'] == 'https://sandbox.mercadopago.com/checkout/test'
    assert mock_post.call_args.kwargs['json']['external_reference'] == '1'
    with app.app_context():
        pedido = Pedido.query.one()
        assert pedido.status == 'PAGAMENTO'
        assert pedido.endereco == 'Rua Direita, Centro - São Paulo/SP - CEP: 01001000'


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
