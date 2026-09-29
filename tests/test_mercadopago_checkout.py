import json
import os
from datetime import datetime
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

    with app.test_client() as client:
        login_response = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login_response.status_code == 200
        assert login_response.get_json()['sucesso'] is True

        with patch('app.routes.requests.post') as mock_post:
            response = client.post('/checkout-infinitepay', json={'frete': 15})

        assert response.status_code == 200
        dados = response.get_json()
        assert dados['sucesso'] is True
        url = dados['url_whatsapp']
        assert url.startswith('https://wa.me/558199475717?text=')
        mensagem = parse_qs(urlparse(url).query)['text'][0]
        assert nome in mensagem
        assert 'Celular: +55 (81) 99999-9999' in mensagem
        assert 'Pedido #1' in mensagem
        assert 'Celular: +55 (81) 99999-9999' in mensagem
        assert '# Produto teste - *P* (Preto) - Ref: REF-TESTE' in mensagem
        assert 'Quantidade: 4 / Valor: R$ 100,00' in mensagem
        assert 'Subtotal: R$ 400,00' in mensagem
        assert 'Frete: R$ 15,00' in mensagem
        assert 'Valor Final: R$ 415,00' in mensagem
        assert 'Forma de Pagamento:\nPIX' in mensagem
        assert 'Forma de Envio:\nExcursão' in mensagem
        assert 'Motorista ou Excursão:\nNome: Não informado' in mensagem
        assert 'Imprimir Pedido:\nhttp://localhost/admin (localize o pedido #1)' in mensagem
        with app.app_context():
            pedido = Pedido.query.get(1)
            assert pedido.status == 'PAGO'
        mock_post.assert_not_called()


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
