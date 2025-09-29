# --- IMPORTS E CONFIGURAÇÕES INICIAIS ---
import eventlet
eventlet.monkey_patch()

import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, join_room, leave_room, emit
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import pytz
from dotenv import load_dotenv
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

load_dotenv()

# --- CONFIGURAÇÃO DO APP FLASK ---
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'uma-chave-secreta-padrao-muito-segura')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tickets.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- INICIALIZAÇÃO DAS EXTENSÕES ---
db = SQLAlchemy(app)
socketio = SocketIO(app, async_mode='eventlet')
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, faça o login para acessar esta página."
login_manager.login_message_category = "info"

# --- MODELOS DO BANCO DE DADOS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    protocolo = db.Column(db.String(20), unique=True, nullable=False)
    nome_cliente = db.Column(db.String(100), nullable=False)
    email_cliente = db.Column(db.String(100), nullable=False)
    setor = db.Column(db.String(50))
    funcao = db.Column(db.String(50))
    descricao = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='Aguardando Resposta')
    data_criacao = db.Column(db.DateTime, default=datetime.now(pytz.timezone('America/Sao_Paulo')))
    anexo = db.Column(db.String(200), nullable=True)

class MensagemChat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_protocolo = db.Column(db.String(20), db.ForeignKey('ticket.protocolo'), nullable=False)
    remetente = db.Column(db.String(100), nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    data_envio = db.Column(db.DateTime, default=datetime.now(pytz.timezone('America/Sao_Paulo')))
    tipo = db.Column(db.String(20), default='mensagem')

# --- FUNÇÕES DE APOIO ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def enviar_email_notificacao(ticket, tipo='abertura'):
    sg = SendGridAPIClient(os.getenv('SENDGRID_API_KEY'))
    remetente_verificado = 'jakelinesouza@hagmachado.com.br'
    
    if tipo == 'abertura':
        assunto = f"Confirmação de Abertura de Ticket: {ticket.protocolo}"
        conteudo = f"""
        Olá {ticket.nome_cliente},  
  

        Seu ticket foi aberto com sucesso com o protocolo <strong>{ticket.protocolo}</strong>.  

        O status inicial é: <strong>{ticket.status}</strong>.  
  

        Nossa equipe de suporte responderá em breve.  
  

        Atenciosamente,  

        Equipe de Suporte HAG
        """
        destinatarios = [ticket.email_cliente, 'jakelinesouza@hagmachado.com.br']
    else: # tipo == 'atualizacao'
        assunto = f"Atualização no seu Ticket: {ticket.protocolo}"
        conteudo = f"""
        Olá {ticket.nome_cliente},  
  

        O status do seu ticket <strong>{ticket.protocolo}</strong> foi atualizado para: <strong>{ticket.status}</strong>.  
  

        Para acompanhar ou falar com o suporte, acesse o sistema.  
  

        Atenciosamente,  

        Equipe de Suporte HAG
        """
        destinatarios = [ticket.email_cliente]

    for destinatario in destinatarios:
        message = Mail(
            from_email=remetente_verificado,
            to_emails=destinatario,
            subject=assunto,
            html_content=conteudo
        )
        try:
            response = sg.send(message)
            print(f"E-mail enviado para {destinatario} via SendGrid. Status: {response.status_code}")
        except Exception as e:
            print(f"Erro ao enviar e-mail para {destinatario}: {e}")

# --- ROTAS DA APLICAÇÃO ---

# NOVA ROTA PRINCIPAL (PORTAL)
@app.route('/')
def index():
    return render_template('index.html')

# NOVA ROTA PARA O FORMULÁRIO DE ABERTURA
@app.route('/abrir-ticket', methods=['GET', 'POST'])
def abrir_ticket():
    if request.method == 'POST':
        fuso_horario = pytz.timezone('America/Sao_Paulo')
        protocolo = f"TICKET-{datetime.now(fuso_horario).strftime('%Y%m%d%H%M%S')}"
        
        novo_ticket = Ticket(
            protocolo=protocolo,
            nome_cliente=request.form['nome'],
            email_cliente=request.form['email'],
            setor=request.form['setor'],
            funcao=request.form['funcao'],
            descricao=request.form['descricao'],
        )
        db.session.add(novo_ticket)
        db.session.commit()

        enviar_email_notificacao(novo_ticket, tipo='abertura')
        
        return redirect(url_for('ticket_criado', protocolo=protocolo))
    
    # Se for GET, apenas renderiza o formulário
    return render_template('abrir_ticket.html')


@app.route('/ticket_criado/<protocolo>')
def ticket_criado(protocolo):
    return render_template('ticket_criado.html', protocolo=protocolo)

# --- ROTAS DE AUTENTICAÇÃO E DASHBOARD (sem alterações) ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Credenciais inválidas. Por favor, tente novamente.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/registrar', methods=['GET', 'POST'])
@login_required
def registrar():
    if not current_user.is_admin:
        flash('Acesso negado. Apenas administradores podem registrar novos usuários.', 'danger')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form['email']
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Este e-mail já está em uso.', 'warning')
            return redirect(url_for('registrar'))
        
        novo_usuario = User(
            nome=request.form['nome'],
            email=email,
            is_admin= 'is_admin' in request.form
        )
        novo_usuario.set_password(request.form['password'])
        db.session.add(novo_usuario)
        db.session.commit()
        flash('Novo usuário registrado com sucesso!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('registrar.html')

@app.route('/dashboard')
@login_required
def dashboard():
    tickets = Ticket.query.order_by(Ticket.data_criacao.desc()).all()
    return render_template('dashboard.html', tickets=tickets)

@app.route('/ticket/<protocolo>', methods=['GET', 'POST'])
@login_required
def gerenciar_ticket(protocolo):
    ticket = Ticket.query.filter_by(protocolo=protocolo).first_or_404()
    if request.method == 'POST':
        novo_status = request.form.get('status')
        comentario = request.form.get('comentario')

        if novo_status and novo_status != ticket.status:
            ticket.status = novo_status
            enviar_email_notificacao(ticket, tipo='atualizacao')
        
        if comentario:
            nova_mensagem = MensagemChat(
                ticket_protocolo=protocolo,
                remetente=f"Suporte ({current_user.nome})",
                mensagem=comentario,
                tipo='comentario'
            )
            db.session.add(nova_mensagem)
        
        db.session.commit()
        flash('Ticket atualizado com sucesso!', 'success')
        return redirect(url_for('gerenciar_ticket', protocolo=protocolo))

    mensagens = MensagemChat.query.filter_by(ticket_protocolo=protocolo).order_by(MensagemChat.data_envio).all()
    return render_template('ticket_detalhes.html', ticket=ticket, mensagens=mensagens)

# --- ROTAS DE CHAT (sem alterações) ---
@app.route('/chat/<protocolo>')
def chat(protocolo):
    ticket = Ticket.query.filter_by(protocolo=protocolo).first_or_404()
    mensagens = MensagemChat.query.filter_by(ticket_protocolo=protocolo).order_by(MensagemChat.data_envio).all()
    return render_template('chat.html', ticket=ticket, mensagens=mensagens)

@socketio.on('join')
def on_join(data):
    username = data['username']
    room = data['room']
    join_room(room)
    
    if username != 'Suporte':
        remetente = username
    else:
        remetente = f"Suporte ({current_user.nome if current_user.is_authenticated else 'Anônimo'})"

    nova_mensagem = MensagemChat(
        ticket_protocolo=room,
        remetente=remetente,
        mensagem=f'{username} entrou no chat.',
        tipo='evento'
    )
    db.session.add(nova_mensagem)
    db.session.commit()
    emit('message', {'remetente': 'Sistema', 'mensagem': f'{username} entrou no chat.', 'tipo': 'evento'}, to=room)

@socketio.on('leave')
def on_leave(data):
    username = data['username']
    room = data['room']
    leave_room(room)
    emit('message', {'remetente': 'Sistema', 'mensagem': f'{username} saiu do chat.', 'tipo': 'evento'}, to=room)

@socketio.on('send_message')
def handle_send_message_event(data):
    room = data['room']
    
    nova_mensagem = MensagemChat(
        ticket_protocolo=room,
        remetente=data['remetente'],
        mensagem=data['mensagem'],
        tipo='mensagem'
    )
    db.session.add(nova_mensagem)
    db.session.commit()
    
    emit('message', data, to=room)

# --- COMANDO PARA CRIAR O BANCO DE DADOS ---
@app.cli.command("create-db")
def create_db():
    """Cria as tabelas do banco de dados e o usuário admin."""
    with app.app_context():
        db.create_all()
        print("Banco de dados criado.")
        if not User.query.filter_by(email='jakelinesouza@hagmachado.com.br').first():
            admin = User(
                nome='Jakeline Souza (Admin)',
                email='jakelinesouza@hagmachado.com.br',
                is_admin=True
            )
            admin.set_password('Templo@25')
            db.session.add(admin)
            db.session.commit()
            print("Usuário administrador criado com sucesso.")
        else:
            print("Usuário administrador já existe.")

# --- EXECUÇÃO DA APLICAÇÃO ---
if __name__ == '__main__':
    socketio.run(app, debug=True)
