# Multi Seat Arch

Interface visual estilo ASTER para configurar multiseat em Arch Linux/CachyOS usando uma única GPU com DRM leasing.

O projeto é uma reimplementação focada em segurança e usabilidade, baseada nas ideias do `garlett/multiseat`: DRM lease manager + wlroots/labwc, um compositor por saída física e dispositivos atribuídos por seat.

## O que a versão 0.3 faz

- detecta monitores, teclados, mouses, touchpads e gamepads automaticamente;
- usa `udev` + caminhos reais de `sysfs`, incluindo USB, Bluetooth HID, I²C e serio;
- mostra Seat A e Seat B visualmente, com monitor, usuário e liga/desliga por seat;
- possui uma tabela central de periféricos com cinco destinos: **Seat A**, **Seat B**, **Compartilhado**, **Desativado** e **Sistema / seat0**;
- move periféricos entre seats em tempo real quando o multiseat já está ativo;
- compartilha teclado/mouse/touchpad/gamepad entre seats por `EVIOCGRAB` + clones `uinput`;
- desativa inputs capturando e descartando os eventos enquanto o multiseat está ativo;
- detecta hotplug e reaplica regras quando um periférico é removido/reconectado;
- mantém dispositivos com `ID_SERIAL` associados mesmo ao trocar de porta USB;
- mantém o controlador Bluetooth global e permite rotear individualmente os dispositivos Bluetooth HID;
- possui distribuição automática para notebooks (eDP = internos; HDMI/DP = USB/Bluetooth);
- valida dependências, usuários, monitores e configuração antes de derrubar a sessão gráfica;
- faz rollback automático para `graphical.target` se a ativação falhar;
- nunca muda permanentemente o target padrão de boot;
- possui **Restaurar PC normal**, que encerra seats/proxies/DRM leases e devolve inputs ao `seat0`.

Detalhes do comportamento ASTER-like: [docs/ASTER_LIKE.md](docs/ASTER_LIKE.md).

## Instalação no CachyOS/Arch

```bash
git clone https://github.com/VitorMartinsAlves/multi-seat-arch.git
cd multi-seat-arch
bash scripts/install.sh
```

O instalador configura a aplicação, `python-evdev` e o módulo `uinput`. Quando necessário, compila a engine de DRM lease (`drm-lease-manager`, wlroots com patch e labwc).

A engine é validada com `ldd`; `/usr/local/lib` é registrado via `ldconfig`, evitando o problema `libdlmclient.so.0 => not found`.

O instalador também detecta e desfaz somente a modificação exata que versões antigas do `garlett/multiseat` faziam em `/usr/lib/udev/rules.d/71-seat.rules`.

## Interface

Abra **Multi Seat Arch** no menu ou execute:

```bash
multi-seat-arch-gui
```

Fluxo recomendado:

1. **Detectar hardware**.
2. usar **Distribuir automaticamente** ou escolher cada destino manualmente.
3. selecionar monitor e usuário de cada seat.
4. escolher para cada periférico: Seat A, Seat B, Compartilhado, Desativado ou Sistema/seat0.
5. clicar em **Validar**.
6. clicar em **Aplicar e iniciar / reiniciar**.

Depois que o multiseat estiver ativo, **Aplicar periféricos agora** troca as rotas sem reiniciar os seats. Essa operação é bloqueada no desktop normal para evitar mover teclado/mouse para seats inexistentes.

A sessão gráfica atual é encerrada durante a ativação completa porque o `drm-lease-manager` precisa assumir o DRM master. Isso vale apenas para a execução atual; o boot padrão continua gráfico.

## Bluetooth

O adaptador/controlador Bluetooth (`hci0`, etc.) permanece global. Dispositivos de entrada Bluetooth — teclado, mouse e controles — aparecem na tabela e podem ser movidos, compartilhados ou desativados como qualquer input.

**Áudio Bluetooth não é duplicado pelo proxy de input.** Áudio continua sendo gerenciado por PipeWire/ALSA e precisa de roteamento de áudio próprio por sessão/dispositivo.

## CLI

```bash
multi-seat-arch discover
multi-seat-arch doctor
multi-seat-arch status
multi-seat-arch validate /etc/multi-seat-arch/config.json
sudo multi-seat-arch apply /caminho/config.json
sudo multi-seat-arch apply-sync /caminho/config.json
sudo multi-seat-arch apply-start /caminho/config.json
sudo multi-seat-arch sync
sudo multi-seat-arch restore
```

`apply-sync` salva + aplica os periféricos em uma única autorização. `apply-start` salva + agenda a ativação completa. `start` e `restore` usam helpers root destacados via `systemd-run`, portanto continuam executando mesmo quando a sessão gráfica que iniciou a ação é encerrada.

## Segurança e recuperação

O projeto não cria usuários silenciosamente, não usa `shell=True`, não cria symlinks improvisados em `/usr/lib`, rejeita root/system como usuário de seat, verifica `ID_SEAT` depois de `loginctl attach`, usa unidades transitórias `systemd --collect` e faz rollback em falhas de ativação.

Recuperação manual:

```bash
sudo multi-seat-arch restore
```

## Compatibilidade

O mecanismo original foi testado pelo autor upstream em NVIDIA GF7300 e AMD R5 230. Intel Ice Lake não constava como hardware oficialmente testado pelo upstream.

A camada desta aplicação corrige especificamente descoberta/atribuição de input para USB, Bluetooth HID, I²C e serio. O suporte efetivo ao DRM leasing de uma única GPU ainda depende do kernel, driver e compositor da máquina.

## Desenvolvimento e validação

```bash
python -m compileall -q src
python -m unittest discover -s tests -v
bash -n scripts/*.sh
```

O CI executa essas verificações em Python 3.11 e 3.12.

## Créditos e licença

Base conceitual e patch de DRM lease derivados de `garlett/multiseat` (`wlroots-0.20`). Veja [ATTRIBUTION.md](ATTRIBUTION.md).

Licença: GPL-2.0.
