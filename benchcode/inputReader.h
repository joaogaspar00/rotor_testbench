#pragma once
#include <Arduino.h>

// Formato de um comando (uma linha terminada em '\n'):
//   <NOME> [valor1] [valor2] ...     p. ex.: "LED", "LED 1", "POT", "STOP"

// Tamanho máximo de um comando (linha) que o Arduino recebe.
// O que passar disto é ignorado.
const int COMMAND_MAX_CHAR = 200;

// Quantos valores (depois do nome) um comando pode ter
const int MAX_CMD_PARAMS = 10;

// Um comando já partido em pedaços. Os char* apontam para DENTRO do buffer da linha: só são válidos até à próxima chamada ao readInput().
struct Command {
    char* name;                     // nome do comando (p. ex.: LED, POT, STOP)
    int count;                      // quantos valores vêm depois do nome
    char* params[MAX_CMD_PARAMS];   // os valores (p. ex.: "0", "4.2")
};

// Lê os bytes que chegaram pela porta série. Quando uma linha está completa, parte-a para 'cmd' e devolve true. Devolve false se a linha ainda não acabou ou se era inválida (nesse caso já foi enviado um ERROR).
bool readInput(Command& cmd);

// Parte 'line' em nome + valores. ATENÇÃO: altera 'line' (troca os espaços por '\0'). Se falhar, responde com ERROR e devolve false.
bool parseInput(char* line, Command& cmd);

// Mostra o que ficou guardado em 'cmd', numa só linha (para depuração).
void viewInput(const Command& cmd);

// Converte params[i] num número inteiro. Devolve false se não for um número inteiro válido.
bool paramToLong(const Command& cmd, int i, long& value);
