import QtQuick
import QtQuick.Window

Window {
    id: root
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"
    visible: false
    width: Math.round(76 * scaleFactor)
    height: width

    property real sf: scaleFactor
    property string sid: ""
    property string agentSource: "claude"
    property string agentState: "idle"
    property bool needsAttention: false
    property bool dragging: false

    function mainColor() {
        if (needsAttention)
            return "#ef4444"
        if (agentState === "running")
            return "#3b82f6"
        if (agentState === "background")
            return "#8b5cf6"
        return "#33cc55"
    }

    function haloColor() {
        if (needsAttention)
            return "#ffc9c9"
        if (agentState === "running")
            return "#bfdbfe"
        if (agentState === "background")
            return "#ddd6fe"
        return "#bbf7d0"
    }

    Item {
        id: halo
        anchors.fill: parent
        opacity: root.visible ? 1 : 0

        property real phase: 0
        NumberAnimation on phase {
            running: root.visible
            loops: Animation.Infinite
            from: 0
            to: 360
            duration: root.needsAttention ? 1200 : (root.agentState === "running" ? 1500 : 4200)
        }

        Canvas {
            id: canvas
            anchors.fill: parent
            antialiasing: true
            onPaint: {
                var ctx = getContext("2d")
                var w = width
                var h = height
                ctx.clearRect(0, 0, w, h)
                var cx = w / 2
                var cy = h / 2
                var r = Math.min(w, h) * 0.31
                var p = halo.phase * Math.PI / 180
                var color = root.mainColor()
                var glow = root.haloColor()

                ctx.lineCap = "round"
                ctx.shadowColor = glow
                ctx.shadowBlur = root.needsAttention ? 18 * root.sf : 11 * root.sf

                ctx.strokeStyle = glow
                ctx.globalAlpha = root.needsAttention ? 0.42 : 0.28
                ctx.lineWidth = Math.max(8 * root.sf, 4)
                ctx.beginPath()
                ctx.arc(cx, cy, r, 0, Math.PI * 2)
                ctx.stroke()

                ctx.shadowBlur = 0
                ctx.globalAlpha = 1
                ctx.strokeStyle = color
                ctx.lineWidth = Math.max(4 * root.sf, 2)
                var spans = root.needsAttention ? 4 : (root.agentState === "running" ? 3 : 2)
                for (var i = 0; i < spans; i++) {
                    var start = p + i * Math.PI * 2 / spans
                    var len = root.needsAttention ? 0.82 : (root.agentState === "running" ? 1.05 : 1.45)
                    ctx.beginPath()
                    ctx.arc(cx, cy, r, start, start + len)
                    ctx.stroke()
                }
            }
            Connections {
                target: halo
                function onPhaseChanged() { canvas.requestPaint() }
            }
            Connections {
                target: root
                function onAgentStateChanged() { canvas.requestPaint() }
                function onNeedsAttentionChanged() { canvas.requestPaint() }
            }
        }

        Rectangle {
            anchors.centerIn: parent
            width: Math.round(27 * root.sf)
            height: width
            radius: width / 2
            color: "#101318"
            border.width: Math.max(1, Math.round(1 * root.sf))
            border.color: Qt.rgba(1, 1, 1, 0.18)

            Text {
                anchors.centerIn: parent
                text: root.agentSource === "codex" ? "CX" : "C"
                color: root.mainColor()
                font {
                    family: "Microsoft YaHei UI"
                    pixelSize: Math.round(10 * root.sf)
                    bold: true
                }
            }
        }

        Rectangle {
            visible: root.needsAttention
            width: Math.round(11 * root.sf)
            height: width
            radius: width / 2
            color: "#ef4444"
            border.width: Math.max(1, Math.round(1 * root.sf))
            border.color: "#ffe4e6"
            anchors.right: parent.right
            anchors.rightMargin: Math.round(14 * root.sf)
            anchors.top: parent.top
            anchors.topMargin: Math.round(14 * root.sf)
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
            property int pressX: 0
            property int pressY: 0
            property int startX: 0
            property int startY: 0
            property bool moved: false

            onPressed: function(mouse) {
                pressX = mouse.screenX
                pressY = mouse.screenY
                startX = root.x
                startY = root.y
                moved = false
                root.dragging = true
            }
            onPositionChanged: function(mouse) {
                if (!pressed)
                    return
                var dx = mouse.screenX - pressX
                var dy = mouse.screenY - pressY
                if (Math.abs(dx) > 3 || Math.abs(dy) > 3)
                    moved = true
                root.x = startX + dx
                root.y = startY + dy
            }
            onReleased: function(_mouse) {
                root.dragging = false
                bridge.saveAgentOverlayPosition(root.x, root.y)
                if (!moved && root.sid.length > 0)
                    bridge.jump(root.sid)
            }
            onCanceled: {
                root.dragging = false
                bridge.saveAgentOverlayPosition(root.x, root.y)
            }
        }
    }
}
