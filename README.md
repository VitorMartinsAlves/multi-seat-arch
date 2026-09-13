# Multi Seat Arch

Interface visual para configurar multiseat em Arch Linux/CachyOS usando uma única GPU com DRM leasing.

O projeto é uma reimplementação focada em segurança e usabilidade, baseada nas ideias do projeto `garlett/multiseat`: DRM lease manager + wlroots/labwc, um compositor por saída física e dispositivos de entrada atribuídos por seat.

## Objetivos

- detectar monitores, teclados, mouses e touchpads automaticamente;
- criar seats visualmente, sem editar arquivos na mão;
- usar caminhos reais do `udev`/`sysfs`, evitando heurísticas frágeis como `ps2m .`;
- aplicar e desfazer a configuração com um clique;
- nunca alterar o target de boot automaticamente;
- manter um modo de recuperação que devolve tudo ao `seat0`;
- validar dependências e compatibilidade antes de iniciar;
- registrar logs claros para diagnosticar Intel/AMD/NVIDIA.

## Interface

Execute:

```bash
multi-seat-arch-gui
```

Fluxo esperado:

1. **Detectar hardware**
2. selecionar um monitor e usuário para cada seat
3. atribuir teclado/mouse/touchpad pela interface
4. clicar em **Validar**
5. clicar em **Aplicar e iniciar**

O botão **Restaurar PC normal** para os seats, limpa as associações de `loginctl` e retorna os dispositivos ao `seat0`.

## Instalação no CachyOS/Arch

```bash
git clone https://github.com/VitorMartinsAlves/multi-seat-arch.git
cd multi-seat-arch
bash scripts/install.sh
```

Dependências gráficas/runtime: `python`, `python-pyqt6`, `libinput`, `systemd`, `pciutils` e `polkit`.

Para o modo de uma única GPU, `drm-lease-manager` e um `labwc` compatível com DRM lease continuam necessários. O comando `multi-seat-arch doctor` mostra exatamente o que falta.

## CLI

```bash
multi-seat-arch discover
multi-seat-arch doctor
multi-seat-arch validate /etc/multi-seat-arch/config.json
sudo multi-seat-arch apply /etc/multi-seat-arch/config.json
sudo multi-seat-arch start
sudo multi-seat-arch restore
```

## Segurança

Este projeto deliberadamente **não** muda o target padrão para `multi-user.target`, não desabilita o display manager no boot, não cria usuários silenciosamente, não cria symlinks de bibliotecas em `/usr/lib` e não sobrescreve regras globais de `udev` durante a instalação.

## Compatibilidade

O mecanismo original foi testado pelo autor upstream em NVIDIA GF7300 e AMD R5 230. Intel Ice Lake não constava como hardware testado. Neste fork, a detecção e a atribuição de input foram reescritas para trabalhar com `udevadm`/`libinput`, incluindo touchpads I²C, mas suporte real a DRM leasing ainda depende do driver/kernel/compositor da máquina.

## Validação

```bash
python -m unittest discover -s tests -v
python -m compileall -q src
```

O CI executa os testes em todo push/PR.

## Créditos e licença

Base conceitual e partes do fluxo são derivadas de `garlett/multiseat` (`wlroots-0.20`). Veja [ATTRIBUTION.md](ATTRIBUTION.md). Licença GPL-2.0.
