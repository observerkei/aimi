#!/bin/bash

function setup_termux() {
    pkg install -y tur-repo x11-repo
    pkg update
    pkg upgrade -y
    pkg install -y rust python-grpcio binutils \
        libandroid-spawn ninja python-pandas \
        patchelf make cmake

    # install aimi_plugin/action/chat_to_open_url of firefox
    pkg install firefox -y
    pkg install geckodriver -y
}

function setup_ubuntu() {
    apt update
    apt upgrade -y
    apt install -y python3-grpcio binutils \
        python3-pandas \
        patchelf make cmake

    # install aimi_plugin/action/chat_to_open_url of firefox
    apt install firefox -y
    apt install python3-gevent -y
    apt install python3-gevent -y
}

function is_ubuntu() {
     if grep -iq "ubuntu" /etc/os-release ; then
        return 1
    else
        return 0
    fi 
}

if [[ -n "$TERMUX_VERSION" ]]; then
    setup_termux
fi

if [[ is_ubuntu ]]; then
    setup_ubuntu
fi


apt-get install -y python3 python3-distutils python3-pip 

if [[ -n "$TERMUX_VERSION" ]]; then
    cat -A ./requirements.txt | grep -vE "pandas==|gevent==" | sed 's/\$$//' > ./requirements.tmp

    pip3 install -r ./requirements.tmp 
    rm ./requirements.tmp

    exit 0
elif [[ is_ubuntu ]]; then
    cat -A ./requirements.txt | grep -vE "pandas==|gevent==" | sed 's/\$$//' > ./requirements.tmp

    pip3 install -r ./requirements.tmp 
    rm ./requirements.tmp

     exit 0
fi


pip3 install -r ./requirements.txt 

exit 0
