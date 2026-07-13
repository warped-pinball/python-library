# CLI guide

Installing the package adds a `vector` command:

```
vector discover                          # find boards on the LAN
vector status elvira                     # show live game status
vector version elvira                    # show firmware version
vector leaders elvira                    # show the leaderboard
vector read elvira 0x2134 --count 4      # read SRAM bytes
vector write elvira 0x2134 5 --password hunter2
vector snapshot elvira -o dump.bin       # dump full SRAM
vector update elvira --password hunter2  # check for + apply a firmware update
```

Each machine-targeting subcommand accepts a machine name or IP address, plus
`--password/-p` (or `$VECTOR_PASSWORD`), `--timeout` for discovery, and
`--usb [PORT]` to go over USB serial instead of the network.

For USB serial support, install the `usb` extra (adds
[pyserial](https://pypi.org/project/pyserial/)):

```bash
pip install "warpedpinball[usb]"
```

The memory commands (`read`, `write`, `snapshot`) are covered in more detail
in [Reading and writing memory](memory.md#from-the-command-line).
