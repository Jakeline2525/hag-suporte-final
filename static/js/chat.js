document.addEventListener('DOMContentLoaded', () => {
    // Conecta ao servidor Socket.IO que está rodando junto com o Flask
    const socket = io();

    // Pega os elementos da página
    const historico = document.getElementById('historico-mensagens');
    const inputMensagem = document.getElementById('mensagem');
    const btnEnviar = document.getElementById('enviar-mensagem');

    // 1. Ao conectar, avisa o servidor para entrar na sala correta
    socket.on('connect', () => {
        console.log('Conectado ao servidor de chat!');
        socket.emit('join', { username: nomeUsuario, room: protocolo });
    });

    // 2. Ouve por novas mensagens do servidor
    socket.on('message', (data) => {
        adicionarMensagem(data);
    });

    // Função para adicionar uma nova mensagem na tela
    function adicionarMensagem(data) {
        const div = document.createElement('div');
        div.classList.add('message');

        if (data.is_system) {
            div.innerHTML = `<em>${data.msg}</em>`;
            div.classList.add('system-message');
        } 
        else {
            div.innerHTML = `<strong>${data.username}:</strong> ${data.msg}`;
            if (data.username === nomeUsuario) {
                div.classList.add('my-message');
            } else {
                div.classList.add('other-message');
            }
        }
        
        historico.appendChild(div);
        historico.scrollTop = historico.scrollHeight;
    }

    // 3. Função para enviar uma mensagem ao servidor
    function enviarMensagem() {
        const msg = inputMensagem.value;
        if (msg.trim() !== '') {
            socket.emit('message', { username: nomeUsuario, msg: msg, room: protocolo });
            inputMensagem.value = '';
            inputMensagem.focus();
        }
    }

    // Envia a mensagem ao clicar no botão
    btnEnviar.addEventListener('click', enviarMensagem);

    // Envia a mensagem ao pressionar a tecla "Enter"
    inputMensagem.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            enviarMensagem();
        }
    });
});
