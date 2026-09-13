# Multi Seat Arch

Interface visual para configurar multiseat em Arch Linux/CachyOS usando uma única GPU com DRM leasing.

O projeto é uma reimplementação focada em segurança e usabilidade, baseada nas ideias do `garlett/multiseat`: DRM lease manager + wlroots/labwc, um compositor por saída física e dispositivos de entrada atribuídos por seat.

## O que ele resolve

- detecta monitores, teclados, mouses e touchpads automaticamente;
- usa `udev` + caminhos reais de `sysfs`, incluindo touchpads I²C/serio;
- cria dois seats pela interface, sem editar arquivos manualmente;
- possui distribuição automática para notebooks (eDP = periféricos internos; HDMI/DP = USB/Bluetooth);
- valida dependências, usuários, monitores e inputs antes de desligar a sessão atual;
- inicia a troca de sessão em um helper `systemd` destacado, evitando matar o próprio processo da GUI no meio da configuração;
- em caso de erro durante a ativação, tenta rollback automático para `graphical.target`;
- nunca altera o target **padrão** de boot;
- possui **Restaurar PC normal**, que para os seats e devolve os inputs ao `seat0`.

## Instalação no CachyOS/Arch

```bash
git clone https://github.com/VitorMartinsAlves/multi-seat-arch.git
cd multi-seat-arch
bash scripts/install.sh
```

O instalador configura a aplicação e, quando necessário, compila a engine de DRM lease (`drm-lease-manager`, wlroots com patch e labwc).

A engine é validada com `ldd`. `/usr/local/lib` é registrado pelo `ldconfig`, evitando o problema de `libdlmclient.so.0 => not found`.

## Interface

Abra **Multi Seat Arch** no menu ou execute:

```bash
multi-seat-arch-gui
```

Fluxo:

1. **Detectar hardware**
2. opcionalmente usar **Distribuir automaticamente**
3. selecionar monitor, usuário e periféricos de cada seat
4. clicar em **Validar**
5. clicar em **Aplicar e iniciar**

A sessão gráfica atual será encerrada durante a transição porque o `drm-lease-manager` precisa assumir o DRM master. Isso é feito apenas para a execução atual; o boot padrão não é alterado.

## CLI

```bash
multi-seat-arch discover
multi-seat-arch doctor
multi-seat-arch validate /etc/multi-seat-arch/config.json
sudo multi-seat-arch apply /caminho/config.json
sudo multi-seat-arch start
sudo multi-seat-arch restore
```

`start` e `restore` agendam helpers root destacados via `systemd-run`, para que continuem funcionando mesmo quando a sessão gráfica que disparou o comando for encerrada.

## Segurança e recuperação

O projeto:

- não modifica permanentemente `graphical.target`;
- não cria usuários silenciosamente;
- não usa symlinks improvisados de bibliotecas em `/usr/lib`;
- rejeita usuário root/system para seats;
- rejeita periférico ou monitor duplicado;
- verifica a atribuição `ID_SEAT` depois de `loginctl attach`;
- usa `--collect` nas unidades transitórias;
- faz rollback para o desktop normal se a ativação falhar.

Se necessário, a recuperação manual continua disponível:

```bash
sudo multi-seat-arch restore
```

## Compatibilidade

O mecanismo original foi testado pelo autor upstream em NVIDIA GF7300 e AMD R5 230. Intel Ice Lake não constava como hardware oficialmente testado pelo upstream.

A camada desta aplicação corrige especificamente a descoberta/atribuição de input para dispositivos USB, I²C e serio, mas o suporte efetivo a DRM leasing ainda depende do kernel, driver e compositor da máquina.

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
