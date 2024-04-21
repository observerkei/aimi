#!/bin/bash

function setup_termux() {
    pkg install -y tur-repo x11-repo
    pkg update
    pkg install -y rust python-grpcio binutils 

    # install aimi_plugin/action/chat_to_open_url of firefox
    pkg install firefox -y
    pkg install geckodriver -y
}


if [[ -n "$TERMUX_VERSION" ]]; then
    setup_termux
fi


apt-get install -y libandroid-spawn make cmake \
    python3 python3-distutils python3-pip \
     patchelf ninja python-pandas \


pip3 install -r ./requirements.txt 

