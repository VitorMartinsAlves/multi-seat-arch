# ASTER-like device manager

A versão 0.3 adiciona gerenciamento visual de periféricos em tempo real.

## Estados de um periférico

Cada dispositivo de entrada pode ficar em um destes estados:

- **Seat A / Seat B**: o dispositivo físico é anexado ao seat escolhido via `systemd-logind`.
- **Compartilhado**: o dispositivo físico é capturado com `EVIOCGRAB`; o Multi Seat Arch cria um clone `uinput` por seat ativo e replica os eventos para todos eles.
- **Desativado**: o dispositivo físico é capturado e seus eventos são descartados enquanto o multiseat está ativo.
- **Sistema / seat0**: o projeto não gerencia o dispositivo e o deixa no seat padrão.

`Compartilhado` e `Desativado` são reversíveis. **Restaurar PC normal** encerra os proxies e executa `loginctl flush-devices`, devolvendo os inputs ao `seat0`.

## Hotplug

As regras usam uma chave persistente derivada de `ID_SERIAL` quando disponível. Assim, dispositivos com serial mantêm a atribuição mesmo se mudarem de porta USB. Sem serial, a regra fica vinculada ao caminho físico/porta, evitando confundir dois periféricos idênticos.

Um watcher root detecta mudanças no inventário de `evdev` e reaplica a configuração. Regras de dispositivos desconectados permanecem salvas e voltam a valer quando o hardware reaparece.

## Bluetooth

O controlador Bluetooth (`hciN`) permanece global. Teclados, mouses e controles Bluetooth aparecem como dispositivos `evdev` e podem ser atribuídos, compartilhados ou desativados normalmente. Isso evita mover o adaptador inteiro entre seats e quebrar o pareamento.

Bluetooth de áudio não é duplicado pelo proxy de input: áudio continua sob PipeWire/ALSA e exige roteamento próprio por sessão.

## Segurança operacional

A operação **Aplicar periféricos agora** só funciona quando pelo menos um seat do Multi Seat Arch está realmente ativo. Isso impede que `loginctl flush-devices` mova teclado/mouse para seats inexistentes durante uma sessão gráfica normal.

A ativação completa continua sendo executada por um helper destacado do desktop, com rollback para `graphical.target` em caso de falha.
