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
        interval: 6000
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
                    text: "> AI-2 █"
                    font.family: "monospace"
                    font.pixelSize: 64
                    font.bold: true
                    color: "#35D07F"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "your old PC gets a new AI brain"
                    font.family: "monospace"
                    font.pixelSize: 24
                    color: "#B8F5D0"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Based on Artix Linux"
                    font.family: "monospace"
                    font.pixelSize: 16
                    color: "#6B7A72"
                }
            }
        }
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
                    text: "honest about your hardware"
                    font.family: "monospace"
                    font.pixelSize: 32
                    font.bold: true
                    color: "#35D07F"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: "ai-2 benchmark measures what this machine can really do\nand recommends models that actually fit,\nlocal when possible, remote when not."
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
            Column {
                anchors.centerIn: parent
                spacing: 18
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "first steps"
                    font.family: "monospace"
                    font.pixelSize: 32
                    font.bold: true
                    color: "#35D07F"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignLeft
                    text: "$ ai-2 detect      what this machine is\n$ ai-2 tier        which tier it lands in\n$ ai-2 init        tune it for AI work\n$ ai-2 benchmark   measure it, get your AI Score"
                    font.family: "monospace"
                    font.pixelSize: 18
                    color: "#B8F5D0"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "amber accents mark what needs your attention"
                    font.family: "monospace"
                    font.pixelSize: 14
                    color: "#FFB454"
                }
            }
        }
    }
}
