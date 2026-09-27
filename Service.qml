import QtQuick
import Quickshell.Io

// Loaded once by Omarchy after Enable. No timer, daemon or silent updater.
Item {
    visible: false
    Process {
        id: bootstrap
        command: ["python3", decodeURIComponent(Qt.resolvedUrl("bootstrap.py").toString()).replace(/^file:\/\//, "")]
    }
    Component.onCompleted: bootstrap.running = true
}
