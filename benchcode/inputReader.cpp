#include "inputReader.h"


// Buffer que guarda a linha que vai chegando pela porta série, até chegar o '\n'.
// 'static' = só existe dentro deste ficheiro: mais ninguém lhe pode mexer.
static char cmd_input[COMMAND_MAX_CHAR + 1];

// Quantos bytes já estão guardados no cmd_input[]
static int cmd_input_len = 0;

bool readInput(Command& cmd) {
    while (Serial.available()) {     // há bytes à espera?
        char c = Serial.read();        // tira UM byte
        if (c == '\r') continue;       // ignora o '\r' que alguns programas enviam antes do '\n'
        if (c == '\n') {               // fim da linha
            cmd_input[cmd_input_len] = '\0';
            cmd_input_len = 0;               // esvazia o buffer para a próxima
            return parseInput(cmd_input, cmd);   // UMA linha de cada vez: o resto espera pela próxima chamada
        } else if (cmd_input_len < COMMAND_MAX_CHAR) {
            cmd_input[cmd_input_len++] = c;        // guarda o caráter e avança
        }
    }
    return false;                      // a linha ainda não acabou
}

bool parseInput(char* line, Command& cmd) {
    cmd.name = strtok(line, " ");
    if (cmd.name == NULL) {
        Serial.println(F("ERROR empty command: <NAME> [values...]"));
        return false;
    }
    cmd.count = 0;
    char* token = strtok(NULL, " ");
    while (token != NULL) {
        if (cmd.count == MAX_CMD_PARAMS) {     // a lista está cheia: não escrever fora dela
            Serial.print(F("ERROR more than "));
            Serial.print(MAX_CMD_PARAMS);
            Serial.println(F(" values"));
            return false;
        }
        cmd.params[cmd.count++] = token;
        token = strtok(NULL, " ");
    }
    return true;
}

// Mostra o que o parseInput guardou, numa só linha.
void viewInput(const Command& cmd) {
    Serial.print(F("name='"));
    Serial.print(cmd.name);
    Serial.print(F("' count="));
    Serial.print(cmd.count);
    for (int i = 0; i < cmd.count; i++) {
        Serial.print(F(" ["));
        Serial.print(i);
        Serial.print(F("]='"));
        Serial.print(cmd.params[i]);
        Serial.print('\'');
    }
    Serial.println();
}

bool paramToLong(const Command& cmd, int i, long& value) {
    char* end;
    value = strtol(cmd.params[i], &end, 10);         // base 10
    return end != cmd.params[i] && *end == '\0';     // leu alguma coisa E chegou ao fim
}
