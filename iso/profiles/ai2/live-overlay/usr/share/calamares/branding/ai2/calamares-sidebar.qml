/* AI-2 installer sidebar (2026-08-25). Based on Calamares' example
   calamares-sidebar.qml (GPL-3.0-or-later, Adriaan de Groot / Anke Boersma).
   Why QML: the widget sidebar hardcodes the logo to 80x80 px
   (CalamaresWindow.cpp logoLabel->setFixedSize(80,80)), which squeezed or
   shrank the wide AI-2 banner; here the logo takes 85% of the column width
   at its own aspect ratio. Colors all come from branding.desc.
   MUST live in the branding component dir: searchQmlFile("calamares-sidebar")
   checks the branding dir and the QRC only, never /usr/share/calamares/qml. */
import io.calamares.ui 1.0
import io.calamares.core 1.0

import QtQuick 2.3
import QtQuick.Layouts 1.3

Rectangle {
    id: sideBar;
    color: Branding.styleString( Branding.SidebarBackground );
    anchors.fill: parent;

    ColumnLayout {
        anchors.fill: parent;
        spacing: 0;

        Item {
            // logo band: the wide AI-2 banner at 85% of the column width.
            // The 212/76 aspect is the SVG's own viewBox; hardcoded because
            // implicitWidth of an SVG is unreliable at layout time.
            Layout.fillWidth: true;
            Layout.topMargin: 18;
            Layout.bottomMargin: 18;
            Layout.preferredHeight: logo.height;
            Image {
                id: logo;
                anchors.horizontalCenter: parent.horizontalCenter;
                width: parent.width * 0.85;
                height: width * 76 / 212;
                fillMode: Image.PreserveAspectFit;
                source: "file:/" + Branding.imagePath( Branding.ProductLogo );
                sourceSize.width: 640;
                sourceSize.height: 230;
            }
        }

        Repeater {
            model: ViewManager
            Rectangle {
                Layout.leftMargin: 6;
                Layout.rightMargin: 6;
                Layout.fillWidth: true;
                height: 35;
                radius: 6;
                color: Branding.styleString( index == ViewManager.currentStepIndex ? Branding.SidebarBackgroundCurrent : Branding.SidebarBackground );

                Text {
                    anchors.verticalCenter: parent.verticalCenter;
                    anchors.horizontalCenter: parent.horizontalCenter;
                    color: Branding.styleString( index == ViewManager.currentStepIndex ? Branding.SidebarTextCurrent : Branding.SidebarText );
                    font.pointSize: 11;
                    text: display;
                }
            }
        }

        Item {
            Layout.fillHeight: true;
        }

        Rectangle {
            id: metaArea
            Layout.fillWidth: true;
            height: 35
            Layout.alignment: Qt.AlignHCenter | Qt.AlignBottom
            color: Branding.styleString( Branding.SidebarBackground );

            MouseArea {
                id: mouseAreaAbout
                anchors.fill: parent;
                cursorShape: Qt.PointingHandCursor
                hoverEnabled: true
                Text {
                    anchors.verticalCenter: parent.verticalCenter;
                    anchors.horizontalCenter: parent.horizontalCenter;
                    text: qsTr("About")
                    color: Branding.styleString( Branding.SidebarText );
                    opacity: 0.6;
                    font.pointSize : 9
                }
                onClicked: debug.about()
            }
        }
    }
}
