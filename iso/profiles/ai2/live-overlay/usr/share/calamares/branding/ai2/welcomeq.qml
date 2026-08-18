/* AI-2 welcome page for the Calamares "welcomeq" module.
 *
 * Derived from Calamares' src/modules/welcomeq/welcomeq.qml (v3.4.2),
 *   SPDX-FileCopyrightText: 2020 Adriaan de Groot <groot@kde.org>
 *   SPDX-FileCopyrightText: 2020 Anke Boersma <demm@kaosx.us>
 *   SPDX-License-Identifier: GPL-3.0-or-later
 * AI-2 changes (2026-08-18, same license): the language choice comes FIRST,
 * with an explicit "Choose your language" label, instead of an unlabeled
 * combo box at the bottom of the page; plain wording; no support/issues/
 * donate buttons; requirements list below.
 */
import io.calamares.core 1.0
import io.calamares.ui 1.0

import QtQuick 2.10
import QtQuick.Controls 2.10
import QtQuick.Layouts 1.3
import QtQuick.Window 2.3

import "qrc:/"

Page
{
    id: welcome

    header: Item {
        width: parent.width
        height: parent.height

        ColumnLayout {
            id: column
            anchors.top: parent.top
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.topMargin: 24
            width: parent.width * 0.8
            spacing: 18

            Image {
                id: welcomeImage
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredHeight: 96
                // imagePath() returns a full pathname, so make it refer to the filesystem
                source: "file:/" + Branding.imagePath(Branding.ProductWelcome)
                sourceSize.height: 96
                fillMode: Image.PreserveAspectFit
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("<h2>Welcome to the %1 installer</h2>").arg(Branding.string(Branding.ProductName))
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                horizontalAlignment: Text.AlignHCenter
                font.pointSize: 13
                font.bold: true
                text: qsTr("Choose your language:")
            }

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: column.width * 0.7
                spacing: 12

                Image {
                    Layout.preferredHeight: 40
                    Layout.preferredWidth: 40
                    fillMode: Image.PreserveAspectFit
                    source: "qrc:/img/language-icon-48px.png"
                }

                ComboBox {
                    id: languages
                    Layout.fillWidth: true
                    textRole: "label"
                    currentIndex: config.localeIndex
                    model: config.languagesModel
                    onCurrentIndexChanged: config.localeIndex = currentIndex
                }
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: column.width * 0.8
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: qsTr("<p>The next pages ask a few questions (location, keyboard, disk, your user) and then install %1 on this computer.</p><p>Nothing is written to your disks until you confirm the summary and the installation starts.</p>").arg(Branding.string(Branding.ProductName))
            }

            Button {
                Layout.alignment: Qt.AlignHCenter
                text: qsTr("Read the guide (START HERE)")
                icon.name: "help-contents"
                onClicked: Qt.openUrlExternally("file:///usr/share/doc/ai2/START-HERE.txt")
            }

        }

        // The requirements list (only when something is unmet). Calamares'
        // Requirements item anchors.fill its parent, so it gets its own box
        // BELOW the language chooser instead of a slot in the column above.
        Item {
            id: requirementsArea
            anchors.top: column.bottom
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.topMargin: -40
            visible: !config.requirementsModel.satisfiedRequirements

            Requirements {}
        }
    }
}
