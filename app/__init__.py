import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy import inspect, text

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    em_producao = bool(os.environ.get('RENDER') or os.environ.get('RENDER_SERVICE_ID'))
    secret_key = os.environ.get('SECRET_KEY')
    if em_producao and not secret_key:
        raise RuntimeError('Defina SECRET_KEY nas variáveis de ambiente antes de iniciar em produção.')

    database_url = os.environ.get('DATABASE_URL', 'sqlite:///leyly.db')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql+psycopg://', 1)
    elif database_url.startswith('postgresql://'):
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)

    app.config['SECRET_KEY'] = secret_key or 'leyly-local-development-key'
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['UPLOAD_FOLDER'] = os.path.abspath(os.environ.get('UPLOAD_DIR') or os.path.join(app.static_folder, 'uploads'))
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    app.config['MERCADO_PAGO_ACCESS_TOKEN'] = os.environ.get('MERCADO_PAGO_ACCESS_TOKEN', '')
    app.config['WHATSAPP_LOJA'] = os.environ.get('WHATSAPP_LOJA', '5581994597999')
    app.config['ADMIN_EMAIL'] = os.environ.get('ADMIN_EMAIL') or ('' if em_producao else 'admin@leyly.com')
    app.config['ADMIN_PASSWORD'] = os.environ.get('ADMIN_PASSWORD') or ('' if em_producao else 'admin123')

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    static_upload_folder = os.path.join(app.static_folder, 'uploads')
    if os.path.realpath(static_upload_folder) != os.path.realpath(app.config['UPLOAD_FOLDER']):
        if os.path.lexists(static_upload_folder):
            if not os.path.islink(static_upload_folder) or os.path.realpath(static_upload_folder) != os.path.realpath(app.config['UPLOAD_FOLDER']):
                raise RuntimeError(f'{static_upload_folder} precisa ser um link para UPLOAD_DIR.')
        else:
            os.symlink(app.config['UPLOAD_FOLDER'], static_upload_folder, target_is_directory=True)

    db.init_app(app)
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

        colunas_produto = {coluna['name'] for coluna in inspect(db.engine).get_columns('produto')}
        with db.engine.begin() as conexao:
            for coluna in ('preco_p', 'preco_m', 'preco_g', 'preco_gg'):
                if coluna not in colunas_produto:
                    conexao.execute(text(f'ALTER TABLE produto ADD COLUMN {coluna} FLOAT'))
            if 'grade' not in colunas_produto:
                conexao.execute(text('ALTER TABLE produto ADD COLUMN grade TEXT'))
            if 'cores' not in colunas_produto:
                conexao.execute(text('ALTER TABLE produto ADD COLUMN cores TEXT'))
            if 'variantes' not in colunas_produto:
                conexao.execute(text('ALTER TABLE produto ADD COLUMN variantes TEXT'))

    return app