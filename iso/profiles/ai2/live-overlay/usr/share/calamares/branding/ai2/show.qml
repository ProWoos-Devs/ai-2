/* AI-2 install slideshow. Text-only, terminal aesthetic, palette from
 * 000/design/ai2-logo-concepts.txt. Same imports as the stock Artix show.
 */

import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation
{
    id: presentation

    // Paint the whole viewport dark; Slide items are inset by default
    // and would otherwise sit on a white frame.
    Rectangle {
        anchors.fill: parent
        color: "#0B0F0D"
        z: -1
    }

    Timer {
        interval: 8000
        running: true
        repeat: true
        onTriggered: presentation.goToNextSlide()
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#0B0F0D"
            Column {
                anchors.centerIn: parent
                spacing: 18
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: '> AI-2 █'
                    font.family: "monospace"
                    font.pixelSize: 64
                    font.bold: true
                    color: "#35D07F"
                }
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#0B0F0D"
            Text {
                anchors.top: parent.top
                anchors.topMargin: 36
                anchors.horizontalCenter: parent.horizontalCenter
                text: '> AI-2 █'
                font.family: "monospace"
                font.pixelSize: 26
                font.bold: true
                color: "#35D07F"
                opacity: 0.9
            }
            Column {
                anchors.centerIn: parent
                spacing: 18
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr('Knowledge Packs')
                    font.family: "monospace"
                    font.pixelSize: 32
                    font.bold: true
                    color: "#35D07F"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('AI-2 arrives with Knowledge Packs: documents this computer searches\nand answers from in seconds, with no internet, naming its source.\nNo AI writes those answers, so an old PC answers as well as a new one.')
                    font.family: "monospace"
                    font.pixelSize: 18
                    color: "#B8F5D0"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('Applications > AI-2 > Search Knowledge   works right after install.\nAdd more packs, or make one from your own PDFs:  $ ai-2 knowledge available')
                    font.family: "monospace"
                    font.pixelSize: 14
                    color: "#FFB454"
                }
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#0B0F0D"
            // wordmark in the otherwise empty top band (2026-08-25)
            Text {
                anchors.top: parent.top
                anchors.topMargin: 36
                anchors.horizontalCenter: parent.horizontalCenter
                text: '> AI-2 █'
                font.family: "monospace"
                font.pixelSize: 26
                font.bold: true
                color: "#35D07F"
                opacity: 0.9
            }
            Column {
                anchors.centerIn: parent
                spacing: 18
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr('Honest about your hardware')
                    font.family: "monospace"
                    font.pixelSize: 32
                    font.bold: true
                    color: "#35D07F"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('ai-2 benchmark measures what this machine can really do\nand recommends models that actually fit,\nlocal when possible, remote when not.')
                    font.family: "monospace"
                    font.pixelSize: 18
                    color: "#B8F5D0"
                }
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#0B0F0D"
            // wordmark in the otherwise empty top band (2026-08-25)
            Text {
                anchors.top: parent.top
                anchors.topMargin: 36
                anchors.horizontalCenter: parent.horizontalCenter
                text: '> AI-2 █'
                font.family: "monospace"
                font.pixelSize: 26
                font.bold: true
                color: "#35D07F"
                opacity: 0.9
            }
            Column {
                anchors.centerIn: parent
                spacing: 18
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr('First steps')
                    font.family: "monospace"
                    font.pixelSize: 32
                    font.bold: true
                    color: "#35D07F"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('At your first login the setup wizard opens by itself:\nit scans the machine, tunes it, installs the AI engine,\ndownloads a first model and measures your AI Score.')
                    font.family: "monospace"
                    font.pixelSize: 18
                    color: "#B8F5D0"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('then: $ ai-2 chat   opens the chat page in the browser')
                    font.family: "monospace"
                    font.pixelSize: 14
                    color: "#FFB454"
                }
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#0B0F0D"
            // wordmark in the otherwise empty top band (2026-08-25)
            Text {
                anchors.top: parent.top
                anchors.topMargin: 36
                anchors.horizontalCenter: parent.horizontalCenter
                text: '> AI-2 █'
                font.family: "monospace"
                font.pixelSize: 26
                font.bold: true
                color: "#35D07F"
                opacity: 0.9
            }
            Column {
                anchors.centerIn: parent
                spacing: 18
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr('Chat right away, offline')
                    font.family: "monospace"
                    font.pixelSize: 32
                    font.bold: true
                    color: "#35D07F"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('AI-2 ships with a small starter model on board, so the chat\nworks right after install, even with no internet. Being small, it\ncan get facts wrong: for facts, ask the Knowledge Packs instead.')
                    font.family: "monospace"
                    font.pixelSize: 18
                    color: "#B8F5D0"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('Once online, the setup wizard measures this machine\nand offers bigger models that fit your hardware.')
                    font.family: "monospace"
                    font.pixelSize: 14
                    color: "#FFB454"
                }
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#0B0F0D"
            // wordmark in the otherwise empty top band (2026-08-25)
            Text {
                anchors.top: parent.top
                anchors.topMargin: 36
                anchors.horizontalCenter: parent.horizontalCenter
                text: '> AI-2 █'
                font.family: "monospace"
                font.pixelSize: 26
                font.bold: true
                color: "#35D07F"
                opacity: 0.9
            }
            Column {
                anchors.centerIn: parent
                spacing: 18
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr('Your data stays here')
                    font.family: "monospace"
                    font.pixelSize: 32
                    font.bold: true
                    color: "#35D07F"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('The model runs on this computer, on the CPU.\nNo account, no subscription, nothing leaves the machine.\nAn online model is used only if you explicitly choose it.')
                    font.family: "monospace"
                    font.pixelSize: 18
                    color: "#B8F5D0"
                }
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#0B0F0D"
            // wordmark in the otherwise empty top band (2026-08-25)
            Text {
                anchors.top: parent.top
                anchors.topMargin: 36
                anchors.horizontalCenter: parent.horizontalCenter
                text: '> AI-2 █'
                font.family: "monospace"
                font.pixelSize: 26
                font.bold: true
                color: "#35D07F"
                opacity: 0.9
            }
            Column {
                anchors.centerIn: parent
                spacing: 18
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr('Lean by design')
                    font.family: "monospace"
                    font.pixelSize: 32
                    font.bold: true
                    color: "#35D07F"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('AI-2 installs only what it needs: the desktop, a browser,\na text editor and the AI engine. Light on old machines.\nAnything else is one command away:')
                    font.family: "monospace"
                    font.pixelSize: 18
                    color: "#B8F5D0"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('$ sudo pacman -S atril        PDF viewer\n$ sudo pacman -S cups         printing\n$ sudo pacman -S libreoffice-still')
                    font.family: "monospace"
                    font.pixelSize: 14
                    color: "#FFB454"
                }
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#0B0F0D"
            // wordmark in the otherwise empty top band (2026-08-25)
            Text {
                anchors.top: parent.top
                anchors.topMargin: 36
                anchors.horizontalCenter: parent.horizontalCenter
                text: '> AI-2 █'
                font.family: "monospace"
                font.pixelSize: 26
                font.bold: true
                color: "#35D07F"
                opacity: 0.9
            }
            Column {
                anchors.centerIn: parent
                spacing: 18
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr('Based on Artix Linux')
                    font.family: "monospace"
                    font.pixelSize: 32
                    font.bold: true
                    color: "#35D07F"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('Artix is Arch Linux without systemd; AI-2 uses its runit init.\nRolling release: you update, you never reinstall.\nDocumentation: https://wiki.artixlinux.org')
                    font.family: "monospace"
                    font.pixelSize: 18
                    color: "#B8F5D0"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('$ sudo pacman -Syu   updates everything, AI-2 included')
                    font.family: "monospace"
                    font.pixelSize: 14
                    color: "#FFB454"
                }
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#0B0F0D"
            // wordmark in the otherwise empty top band (2026-08-25)
            Text {
                anchors.top: parent.top
                anchors.topMargin: 36
                anchors.horizontalCenter: parent.horizontalCenter
                text: '> AI-2 █'
                font.family: "monospace"
                font.pixelSize: 26
                font.bold: true
                color: "#35D07F"
                opacity: 0.9
            }
            Column {
                anchors.centerIn: parent
                spacing: 18
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr('Your feedback')
                    font.family: "monospace"
                    font.pixelSize: 32
                    font.bold: true
                    color: "#35D07F"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('AI-2 is young. If something does not work on your machine,\nsay so; the hardware you report is the hardware AI-2 gets better on.')
                    font.family: "monospace"
                    font.pixelSize: 18
                    color: "#B8F5D0"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr('Bugs and ideas: https://github.com/ProWoos-Devs/ai-2/issues\nAbout the project: https://prowoos.com/software-development/linux/ai-2/')
                    font.family: "monospace"
                    font.pixelSize: 14
                    color: "#FFB454"
                }
            }
        }
    }
}
