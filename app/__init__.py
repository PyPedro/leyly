import json
import os
import shutil

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy import inspect, text
from authlib.integrations.flask_client import OAuth

db = SQLAlchemy()
login_manager = LoginManager()
oauth = OAuth()

def validar_disco_persistente_uploads(diretorio_uploads, em_producao):
    diretorio = os.path.abspath(diretorio_uploads)
    while em_producao and not os.path.ismount(diretorio):
        diretorio_pai = os.path.dirname(diretorio)
        if diretorio_pai == diretorio:
            raise RuntimeError(
                f'O disco persistente do Render não está montado em {diretorio_uploads} '
                'ou em um diretório pai. Configure o mountPath do disco para conter UPLOAD_DIR.'
            )
        diretorio = diretorio_pai

def configurar_diretorio_uploads(diretorio_estatico, diretorio_persistente, migrar_existentes=False):
    os.makedirs(diretorio_persistente, exist_ok=True)
    if os.path.realpath(diretorio_estatico) == os.path.realpath(diretorio_persistente):
        return

    if os.path.lexists(diretorio_estatico):
        if os.path.islink(diretorio_estatico):
            if os.path.realpath(diretorio_estatico) != os.path.realpath(diretorio_persistente):
                raise RuntimeError(f'{diretorio_estatico} precisa ser um link para UPLOAD_DIR.')
            return
        if not os.path.isdir(diretorio_estatico):
            raise RuntimeError(f'{diretorio_estatico} precisa ser um link para UPLOAD_DIR.')
        if not migrar_existentes:
            raise RuntimeError(f'{diretorio_estatico} precisa ser um link para UPLOAD_DIR.')

        for raiz, _, arquivos in os.walk(diretorio_estatico):
            relativo = os.path.relpath(raiz, diretorio_estatico)
            destino = diretorio_persistente if relativo == '.' else os.path.join(diretorio_persistente, relativo)
            os.makedirs(destino, exist_ok=True)
            for arquivo in arquivos:
                origem_arquivo = os.path.join(raiz, arquivo)
                destino_arquivo = os.path.join(destino, arquivo)
                if not os.path.exists(destino_arquivo):
                    shutil.copy2(origem_arquivo, destino_arquivo)
        shutil.rmtree(diretorio_estatico)

    os.symlink(diretorio_persistente, diretorio_estatico, target_is_directory=True)

def create_app():
    app = Flask(__name__)
    em_producao = bool(os.environ.get('RENDER') or os.environ.get('RENDER_SERVICE_ID'))
    secret_key = os.environ.get('SECRET_KEY')
    if em_producao and not secret_key:
        raise RuntimeError('Defina SECRET_KEY nas variáveis de ambiente antes de iniciar em produção.')

    database_url = os.environ.get('DATABASE_URL', 'sqlite:///leyly.db')
    if em_producao and not database_url.startswith(('postgres://', 'postgresql://', 'postgresql+psycopg://')):
        raise RuntimeError('Em produção, DATABASE_URL deve apontar para um banco PostgreSQL persistente do Render.')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql+psycopg://', 1)
    elif database_url.startswith('postgresql://'):
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)

    app.config['SECRET_KEY'] = secret_key or 'leyly-local-development-key'
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True, 'pool_recycle': 1800}
    app.config['UPLOAD_FOLDER'] = os.path.abspath(os.environ.get('UPLOAD_DIR') or os.path.join(app.static_folder, 'uploads'))
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    app.config['MERCADO_PAGO_ACCESS_TOKEN'] = os.environ.get('MERCADO_PAGO_ACCESS_TOKEN', '')
    app.config['WHATSAPP_LOJA'] = os.environ.get('WHATSAPP_LOJA', '558199475717')
    app.config['CEP_ORIGEM'] = os.environ.get('CEP_ORIGEM', '55750-000')
    app.config['PESO_PRODUTO_GRAMAS'] = int(os.environ.get('PESO_PRODUTO_GRAMAS', '400'))
    app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID', '')
    app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET', '')
    app.config['GOOGLE_LOGIN_ENABLED'] = bool(app.config['GOOGLE_CLIENT_ID'] and app.config['GOOGLE_CLIENT_SECRET'])
    app.config['IS_RENDER'] = em_producao
    app.config['ADMIN_EMAIL'] = os.environ.get('ADMIN_EMAIL') or ('' if em_producao else 'admin@leyly.com')
    app.config['ADMIN_PASSWORD'] = os.environ.get('ADMIN_PASSWORD') or ('' if em_producao else 'admin123')

    static_upload_folder = os.path.join(app.static_folder, 'uploads')
    validar_disco_persistente_uploads(app.config['UPLOAD_FOLDER'], em_producao)
    configurar_diretorio_uploads(static_upload_folder, app.config['UPLOAD_FOLDER'], migrar_existentes=em_producao)

    db.init_app(app)
    oauth.init_app(app)
    google_oauth = None
    if app.config['GOOGLE_LOGIN_ENABLED']:
        google_oauth = oauth.register(
            name='google',
            client_id=app.config['GOOGLE_CLIENT_ID'],
            client_secret=app.config['GOOGLE_CLIENT_SECRET'],
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile'},
        )
    app.extensions['google_oauth'] = google_oauth
    login_manager.init_app(app)
    login_manager.login_view = 'main.index'

    from app.models import Usuario

    @login_manager.user_loader
    def load_user(user_id):
        return Usuario.query.get(int(user_id))

    from app.routes import main_bp
    app.register_blueprint(main_bp)

    with app.app_context():
        db.create_all()
        colunas_usuario = {coluna['name'] for coluna in inspect(db.engine).get_columns('usuario')}
        if 'cliente_especial' not in colunas_usuario:
            with db.engine.begin() as conexao:
                conexao.execute(text('ALTER TABLE usuario ADD COLUMN cliente_especial BOOLEAN NOT NULL DEFAULT FALSE'))
        if 'google_sub' not in colunas_usuario:
            with db.engine.begin() as conexao:
                conexao.execute(text('ALTER TABLE usuario ADD COLUMN google_sub VARCHAR(255)'))
        with db.engine.begin() as conexao:
            conexao.execute(text(
                'CREATE UNIQUE INDEX IF NOT EXISTS uq_usuario_google_sub '
                'ON usuario (google_sub) WHERE google_sub IS NOT NULL'
            ))

        colunas_produto = {coluna['name'] for coluna in inspect(db.engine).get_columns('produto')}
        with db.engine.begin() as conexao:
            if 'promocao' not in colunas_produto:
                conexao.execute(text('ALTER TABLE produto ADD COLUMN promocao BOOLEAN NOT NULL DEFAULT FALSE'))
            if 'ativo' not in colunas_produto:
                conexao.execute(text('ALTER TABLE produto ADD COLUMN ativo BOOLEAN NOT NULL DEFAULT TRUE'))
            for coluna in ('preco_p', 'preco_m', 'preco_g', 'preco_gg'):
                if coluna not in colunas_produto:
                    conexao.execute(text(f'ALTER TABLE produto ADD COLUMN {coluna} FLOAT'))
            if 'grade' not in colunas_produto:
                conexao.execute(text('ALTER TABLE produto ADD COLUMN grade TEXT'))
            if 'cores' not in colunas_produto:
                conexao.execute(text('ALTER TABLE produto ADD COLUMN cores TEXT'))
            if 'variantes' not in colunas_produto:
                conexao.execute(text('ALTER TABLE produto ADD COLUMN variantes TEXT'))
            if 'categoria' not in colunas_produto:
                conexao.execute(text('ALTER TABLE produto ADD COLUMN categoria VARCHAR(60)'))

        colunas_pedido = {coluna['name'] for coluna in inspect(db.engine).get_columns('pedido')}
        with db.engine.begin() as conexao:
            if 'numero_separacao' not in colunas_pedido:
                conexao.execute(text('ALTER TABLE pedido ADD COLUMN numero_separacao INTEGER'))
                pedidos_confirmados = conexao.execute(text(
                    "SELECT id FROM pedido WHERE status IN ('PAGO', 'SEPARACAO', 'ENVIADO', 'CONCLUIDO') ORDER BY id ASC"
                )).all()
                for numero, (pedido_id,) in enumerate(pedidos_confirmados, start=1):
                    conexao.execute(text(
                        'UPDATE pedido SET numero_separacao = :numero WHERE id = :pedido_id'
                    ), {'numero': numero, 'pedido_id': pedido_id})
            if 'nome_cliente' not in colunas_pedido:
                conexao.execute(text('ALTER TABLE pedido ADD COLUMN nome_cliente VARCHAR(100)'))
            if 'observacao' not in colunas_pedido:
                conexao.execute(text('ALTER TABLE pedido ADD COLUMN observacao TEXT'))
            if 'frete_estimado' not in colunas_pedido:
                conexao.execute(text('ALTER TABLE pedido ADD COLUMN frete_estimado FLOAT NOT NULL DEFAULT 0'))
                pedidos_legados = conexao.execute(text('SELECT id, itens, valor_total FROM pedido')).all()
                for pedido_id, itens_json, valor_total in pedidos_legados:
                    try:
                        itens = json.loads(itens_json or '[]')
                        subtotal = sum(float(item.get('preco') or 0) * int(item.get('quantidade') or 0) for item in itens)
                        total_antigo = float(valor_total or 0)
                    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                        continue
                    frete_estimado = max(0, round(total_antigo - subtotal, 2))
                    conexao.execute(text(
                        'UPDATE pedido SET valor_total = :subtotal, frete_estimado = :frete '
                        'WHERE id = :pedido_id'
                    ), {'subtotal': round(subtotal, 2), 'frete': frete_estimado, 'pedido_id': pedido_id})

        duplicados = db.session.execute(text(
            "SELECT lower(trim(codigo)), COUNT(*) FROM produto "
            "WHERE codigo IS NOT NULL AND trim(codigo) <> '' "
            "GROUP BY lower(trim(codigo)) HAVING COUNT(*) > 1"
        )).all()
        if duplicados:
            app.logger.warning('Indice de referencia unica nao criado: existem referencias duplicadas legadas.')
        else:
            try:
                with db.engine.begin() as conexao:
                    conexao.execute(text(
                        'CREATE UNIQUE INDEX IF NOT EXISTS uq_produto_codigo_normalizado '
                        'ON produto (lower(trim(codigo))) '
                        "WHERE codigo IS NOT NULL AND trim(codigo) <> ''"
                    ))
            except Exception:
                app.logger.exception('Nao foi possivel criar o indice unico de referencias de produto.')

    return app