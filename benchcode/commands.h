#pragma once
#include "inputReader.h"     // para a struct Command

// Uma função de comando: recebe o comando já partido e responde com UMA linha.
typedef void (*CommandHandler)(const Command& cmd);

// Uma linha da tabela de comandos (a tabela propriamente dita está no commands.cpp).
struct CommandEntry {
    const char* name;        // p. ex.: "LED"
    int minArgs;             // número mínimo de valores depois do nome
    int maxArgs;             // número máximo de valores depois do nome
    CommandHandler handler;  // a função que executa o comando
    const char* usage;       // formato, usado nas mensagens de erro (p. ex.: "LED [0|1]")
};

// Lê a porta série; quando chega uma linha completa, executa-a e responde com UMA linha.
// Chamar em cada volta do loop().
void processInput();

// Envia eventos: linhas que o Nano envia por iniciativa própria, sempre a começar por "EVT"
// (nunca "OK"/"ERROR", para o servidor as distinguir das respostas).
//   EVT POT <valor>                   -> o pot mexeu
//   EVT ESC <NONE|ARMING|ARMED>       -> a bateria foi ligada/desligada, ou o ESC acabou de armar
// Os dois são enviados também uma vez logo a seguir ao arranque (o servidor fica a saber o estado inicial).
// Chamar em cada volta do loop().
void sendEvents();
