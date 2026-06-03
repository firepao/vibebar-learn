import QtQuick
import QtQuick.Window
import QtQuick.Effects

Window {
    id: root
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"
    visible: true

    // ── Island ────────────────────────────────────────────────────────────────
    Rectangle {
        id: island
        width: parent.width
        anchors.bottom: parent.bottom

        property real sf: scaleFactor
        property bool expanded: false
        property int  collapsedH: Math.round(20 * sf)
        property int  bodyPadding: 0
        property int  animDur: 280
        property int  cardH: Math.round(60 * sf)
        property int  cardSpacing: Math.round(8 * sf)
        property int  slotH: cardH + cardSpacing
        property real animPhase: 0  // shared pulse phase — all dots sync to this
        SequentialAnimation on animPhase {
            running: true; loops: Animation.Infinite
            NumberAnimation { to: 1; duration: 1500; easing.type: Easing.InOutSine }
            NumberAnimation { to: 0; duration: 1500; easing.type: Easing.InOutSine }
        }
        property int  displayCount: 0
        property int  visibleRows: Math.max(1, Math.min(displayCount, 10))
        property int  expandedH: bodyPadding * 2 + visibleRows * slotH
        property string surface: "sessions"
        property bool finishSurfaceActive: surface === "finishNotice"
        property int finishH: Math.round(104 * sf)
        property int targetH: finishSurfaceActive ? finishH : expandedH

        property string notifySid: ""
        property string notifyTitle: ""
        property string notifyCwdName: ""
        property string notifyPrompt: ""
        property string notifyReason: "completed"
        property string notifySource: "claude"
        property var notifyQueue: []
        property bool notifyEntered: false
        property bool clearFinishAfterCollapse: false
        property bool notifyIsError: notifyReason === "interrupted" || notifyReason === "stale"
        property bool notifyVisible: notifyTitle.length > 0

        Component.onCompleted: displayCount = sessionsModel.sessionCount

        function hasActiveInteraction() {
            return hoverHandler.hovered
                || islandDragH.active
                || cardsList.cardDragging
                || cardsList.cardHorzDragging
                || emptyStateDragH.active
        }

        function hasActiveDrag() {
            return islandDragH.active
                || cardsList.cardDragging
                || cardsList.cardHorzDragging
                || emptyStateDragH.active
        }

        function enqueueFinishNotice(sid, reason, title, cwdName, prompt, source) {
            var notice = {
                sid: sid,
                reason: reason,
                title: title,
                cwdName: cwdName,
                prompt: prompt,
                source: source
            }
            if ((finishSurfaceActive && notifyVisible) || hasActiveDrag()) {
                var q = notifyQueue.slice()
                q.push(notice)
                notifyQueue = q
                return
            }
            showFinishNotice(notice)
        }

        function showFinishNotice(notice) {
            finishNoticeTimer.stop()
            finishLeaveTimer.stop()
            leaveTimer.stop()
            expandTimer.stop()
            clearFinishAfterCollapse = false
            notifySid = notice.sid
            notifyReason = notice.reason
            notifyTitle = notice.title
            notifyCwdName = notice.cwdName
            notifyPrompt = notice.prompt
            notifySource = notice.source
            notifyEntered = hoverHandler.hovered
            surface = "finishNotice"
            if (!hasActiveDrag())
                expanded = true
            finishNoticeTimer.restart()
        }

        function clearFinishNotice() {
            clearFinishAfterCollapse = false
            notifySid = ""
            notifyTitle = ""
            notifyCwdName = ""
            notifyPrompt = ""
            notifyReason = "completed"
            notifySource = "claude"
            notifyEntered = false
            surface = "sessions"
        }

        function showQueuedFinishNoticeIfIdle() {
            if (finishSurfaceActive || hasActiveDrag() || notifyQueue.length === 0)
                return false
            var q = notifyQueue.slice()
            var next = q.shift()
            notifyQueue = q
            showFinishNotice(next)
            return true
        }

        function showNextFinishNoticeOrCollapse() {
            if (notifyEntered && hoverHandler.hovered) {
                return
            }
            if (notifyQueue.length > 0) {
                var q = notifyQueue.slice()
                var next = q.shift()
                notifyQueue = q
                showFinishNotice(next)
                return
            }
            if (!hasActiveInteraction()) {
                clearFinishAfterCollapse = true
                expanded = false
            } else {
                clearFinishNotice()
            }
        }

        function dismissFinishNoticeAfterLeave() {
            finishNoticeTimer.stop()
            notifyEntered = false
            if (notifyQueue.length > 0) {
                var q = notifyQueue.slice()
                var next = q.shift()
                notifyQueue = q
                showFinishNotice(next)
                return
            }
            if (!islandDragH.active && !cardsList.cardHorzDragging && !emptyStateDragH.active) {
                clearFinishAfterCollapse = true
                expanded = false
            } else {
                clearFinishNotice()
            }
        }

        Connections {
            target: bridge
            function onCollapseRequested() {
                expandTimer.stop()
                leaveTimer.stop()
                if (island.finishSurfaceActive && island.notifyVisible)
                    return
                finishNoticeTimer.stop()
                finishLeaveTimer.stop()
                island.expanded = false
            }
            function onSessionFinished(sid, reason, title, cwdName, prompt, source) {
                island.enqueueFinishNotice(sid, reason, title, cwdName, prompt, source)
            }
        }

        Connections {
            target: sessionsModel
            function onCountChanged() {
                if (sessionsModel.sessionCount < island.displayCount)
                    shrinkDelay.restart()
                else if (sessionsModel.sessionCount !== island.displayCount)
                    island.displayCount = sessionsModel.sessionCount
            }
        }
        Timer {
            id: shrinkDelay
            interval: 220
            onTriggered: island.displayCount = sessionsModel.sessionCount
        }

        property real _maskH: 0   // last height committed to Win32 mask

        height: expanded ? targetH : collapsedH
        Behavior on height {
            NumberAnimation {
                id: heightAnim
                duration: island.animDur; easing.type: Easing.OutCubic
                onRunningChanged: {
                    if (!running) {
                        if (island.expanded) {
                            island._maskH = island.height
                            bridge.onExpandStart(island.height)
                        } else if (island.clearFinishAfterCollapse) {
                            island.clearFinishNotice()
                        }
                    }
                }
            }
        }

        Timer {
            id: collapseShrinkTimer
            interval: 300
            onTriggered: bridge.onCollapseDone(island.collapsedH)
        }

        onExpandedChanged: {
            if (expanded) {
                collapseShrinkTimer.stop()
                _maskH = targetH
                bridge.onExpandStart(targetH)
            } else {
                collapseShrinkTimer.restart()
            }
        }
        onHeightChanged: {
            if (expanded && height > _maskH) {
                _maskH = height
                bridge.onExpandStart(height)
            }
        }
        onTargetHChanged: {
            if (expanded && targetH > _maskH) {
                _maskH = targetH
                bridge.onExpandStart(targetH)
            }
        }

        radius: Math.round(12 * sf)
        color: island.expanded ? "transparent" : "#15171d"
        Behavior on color { ColorAnimation { duration: 200 } }

        layer.enabled: true
        layer.effect: MultiEffect {
            maskEnabled: true
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
            maskSource: ShaderEffectSource {
                width: island.width
                height: island.height
                sourceItem: Rectangle {
                    width: island.width
                    height: island.height
                    radius: island.radius
                    color: "black"
                }
            }
        }

        HoverHandler {
            id: hoverHandler
            onHoveredChanged: {
                if (island.finishSurfaceActive) {
                    if (hovered) {
                        leaveTimer.stop()
                        finishLeaveTimer.stop()
                        expandTimer.stop()
                        island.notifyEntered = true
                    } else {
                        expandTimer.stop()
                        if (!islandDragH.active && !cardsList.cardHorzDragging && !emptyStateDragH.active)
                            finishLeaveTimer.restart()
                    }
                    return
                }
                if (hovered) {
                    leaveTimer.stop()
                    expandTimer.restart()
                } else {
                    expandTimer.stop()
                    if (!islandDragH.active && !cardsList.cardHorzDragging && !emptyStateDragH.active)
                        leaveTimer.restart()
                }
            }
        }
        Timer { id: leaveTimer;  interval: 250; onTriggered: island.expanded = false }
        Timer { id: expandTimer; interval: 0;   onTriggered: island.expanded = true  }
        Timer {
            id: finishNoticeTimer
            interval: 3000
            onTriggered: island.showNextFinishNoticeOrCollapse()
        }
        Timer {
            id: finishLeaveTimer
            interval: 120
            onTriggered: island.dismissFinishNoticeAfterLeave()
        }

        DragHandler {
            id: islandDragH
            target: null
            acceptedButtons: Qt.LeftButton
            dragThreshold: Math.round(8 * island.sf)
            xAxis.enabled: true
            yAxis.enabled: false
            enabled: !island.expanded
            onActiveChanged: {
                if (active) {
                    expandTimer.stop()
                    bridge.startIslandDrag()
                } else {
                    bridge.endIslandDrag()
                    if (island.showQueuedFinishNoticeIfIdle()) return
                    if (hoverHandler.hovered) expandTimer.restart()
                    else leaveTimer.restart()
                }
            }
            onActiveTranslationChanged: {
                if (active) bridge.moveIslandX()
            }
        }

        // ── Collapsed: dot strip ──────────────────────────────────────────────
        Item {
            id: dotStrip
            z: 2
            anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter }
            height: island.collapsedH
            width: Math.max(Math.round(10 * island.sf), dotRow.implicitWidth)
            opacity: island.expanded ? 0.0 : 1.0
            Behavior on opacity { NumberAnimation { duration: island.expanded ? 120 : island.animDur } }

            Row {
                id: dotRow
                anchors.centerIn: parent
                spacing: Math.round(8 * island.sf)

                Rectangle {
                    visible: sessionsModel.sessionCount === 0
                    width: Math.round(10 * island.sf); height: Math.round(10 * island.sf)
                    radius: Math.round(5 * island.sf)
                    color: "#5e6678"
                    anchors.verticalCenter: parent.verticalCenter
                }

                Repeater {
                    model: sessionsModel
                    delegate: Rectangle {
                        required property string dotColor
                        required property bool   isRunning
                        required property bool   isAttention
                        required property bool   isBackground
                        width: Math.round(10 * island.sf); height: Math.round(10 * island.sf)
                        radius: Math.round(5 * island.sf)
                        anchors.verticalCenter: parent.verticalCenter
                        color: {
                            var p = island.animPhase
                            if (isAttention)
                                return Qt.rgba((122+117*p)/255, (26+42*p)/255, (26+42*p)/255, 1)
                            if (isRunning)
                                return Qt.rgba((91+48*p)/255, (33+59*p)/255, (182+64*p)/255, 1)
                            if (isBackground)
                                return Qt.rgba((30+29*p)/255, (58+72*p)/255, (138+108*p)/255, 1)
                            return dotColor
                        }
                    }
                }
            }
        }

        // ── Expanded: session cards ───────────────────────────────────────────
        Item {
            id: expandedArea
            anchors { fill: parent; margins: island.bodyPadding }
            enabled: island.expanded
            opacity: {
                var range = island.targetH - island.collapsedH
                if (range <= 0) return island.expanded ? 1.0 : 0.0
                var fadeStartH = island.collapsedH + range * 0.5
                if (island.height >= fadeStartH) return 1.0
                if (island.height <= island.collapsedH) return 0.0
                return (island.height - island.collapsedH) / (fadeStartH - island.collapsedH)
            }

            Rectangle {
                visible: sessionsModel.sessionCount === 0 && !island.finishSurfaceActive
                anchors.centerIn: parent
                width: parent.width
                height: island.cardH
                radius: Math.round(16 * island.sf)
                color: "#1a1d25"

                DragHandler {
                    id: emptyStateDragH
                    target: null
                    acceptedButtons: Qt.LeftButton
                    dragThreshold: Math.round(8 * island.sf)
                    xAxis.enabled: true
                    yAxis.enabled: false
                    onActiveChanged: {
                        bridge.setDragging(active)
                        if (active) {
                            expandTimer.stop()
                            bridge.startIslandDrag()
                        } else {
                            bridge.endIslandDrag()
                            if (island.showQueuedFinishNoticeIfIdle()) return
                            if (hoverHandler.hovered) expandTimer.restart()
                            else leaveTimer.restart()
                        }
                    }
                    onActiveTranslationChanged: {
                        if (active) bridge.moveIslandX()
                    }
                }

                Text {
                    anchors.centerIn: parent
                    text: "Waiting for Claude Code sessions…"
                    color: "#5e6678"
                    font { family: "Microsoft YaHei UI"; pixelSize: Math.round(12 * island.sf) }
                }
            }

            ListView {
                id: cardsList
                anchors.fill: parent
                spacing: 0
                clip: true
                visible: !island.finishSurfaceActive
                model: sessionsModel

                property real dragComp: 0
                property int  dragSlot: -1
                property bool cardDragging: false
                property bool cardHorzDragging: false

                // ── Card delegate ─────────────────────────────────────────────
                delegate: Item {
                    id: cardDelegate
                    required property string sid
                    required property string cwdName
                    required property string lastPrompt
                    required property string status
                    required property string elapsed
                    required property string dotColor
                    required property bool   isRunning
                    required property bool   isAttention
                    required property bool   isBackground
                    required property string bgColor
                    required property string source
                    required property int    index

                    property bool _closing: false

                    width: cardsList.width
                    height: island.slotH
                    clip: _closing   // clip only during collapse, not during drag
                    z: dragH.active ? 2 : 1

                    states: State {
                        name: "closing"; when: cardDelegate._closing
                        PropertyChanges { target: cardDelegate; height: 0; opacity: 0 }
                    }
                    transitions: Transition {
                        from: ""; to: "closing"
                        ParallelAnimation {
                            NumberAnimation { property: "height";  duration: 280; easing.type: Easing.OutCubic }
                            NumberAnimation { property: "opacity"; duration: 220; easing.type: Easing.OutCubic }
                        }
                    }

                    Timer {
                        id: closeTimer
                        interval: 280
                        onTriggered: {
                            if (island.displayCount > 1) island.displayCount -= 1
                            bridge.closeSession(cardDelegate.sid)
                        }
                    }

                    // ── Visual card (cardH tall, sits at top of slotH delegate) ──
                    Rectangle {
                        id: cardVisual
                        width: parent.width
                        height: island.cardH
                        anchors.top: parent.top
                        radius: Math.round(16 * island.sf)
                        color: bgColor
                        transform: Translate { y: (dragH.active && dragH._mode === 2) ? (dragH.activeTranslation.y + cardsList.dragComp) : 0 }

                        DragHandler {
                            id: dragH
                            target: null
                            acceptedButtons: Qt.LeftButton
                            dragThreshold: Math.round(8 * island.sf)
                            property int _mode: 0  // 0=undecided 1=island-move 2=card-sort
                            onActiveChanged: {
                                bridge.setDragging(active)
                                if (active) {
                                    cardsList.cardDragging = true
                                    _mode = 0
                                    cardsList.dragSlot = index
                                    cardsList.dragComp = 0
                                } else {
                                    if (_mode === 1) bridge.endIslandDrag()
                                    cardsList.dragSlot = -1
                                    cardsList.cardHorzDragging = false
                                    _mode = 0
                                    cardsList.cardDragging = false
                                    if (island.showQueuedFinishNoticeIfIdle()) return
                                }
                            }
                            onActiveTranslationChanged: {
                                if (!active) return
                                if (_mode === 0) {
                                    var ax = Math.abs(activeTranslation.x)
                                    var ay = Math.abs(activeTranslation.y)
                                    if (ax > ay)      { _mode = 1; cardsList.cardHorzDragging = true; bridge.startIslandDrag() }
                                    else if (ay > ax) { _mode = 2 }
                                    return
                                }
                                if (_mode === 1) {
                                    bridge.moveIslandX()
                                } else {
                                    if (cardsList.dragSlot < 0) return
                                    var visualY = cardsList.dragSlot * island.slotH + activeTranslation.y + cardsList.dragComp
                                    var newSlot = Math.max(0, Math.min(sessionsModel.sessionCount - 1,
                                                                       Math.round(visualY / island.slotH)))
                                    if (newSlot !== cardsList.dragSlot) {
                                        cardsList.dragComp += (cardsList.dragSlot - newSlot) * island.slotH
                                        bridge.moveSessionByIndex(cardsList.dragSlot, newSlot)
                                        cardsList.dragSlot = newSlot
                                    }
                                }
                            }
                        }

                        HoverHandler { id: cardHover }

                        Rectangle {
                            anchors.fill: parent
                            radius: parent.radius
                            color: "#ffffff"
                            opacity: (island.height >= island.expandedH && (cardHover.hovered || dragH.active)) ? 0.12 : 0.0
                            Behavior on opacity { NumberAnimation { duration: 100 } }
                        }

                        Rectangle {
                            id: statusDot
                            width: Math.round(8 * island.sf); height: Math.round(8 * island.sf)
                            radius: Math.round(4 * island.sf)
                            anchors { left: parent.left; leftMargin: Math.round(14 * island.sf); verticalCenter: parent.verticalCenter }
                            color: {
                                var p = island.animPhase
                                if (isAttention)
                                    return Qt.rgba((122+117*p)/255, (26+42*p)/255, (26+42*p)/255, 1)
                                if (isRunning)
                                    return Qt.rgba((91+48*p)/255, (33+59*p)/255, (182+64*p)/255, 1)
                                if (isBackground)
                                    return Qt.rgba((30+29*p)/255, (58+72*p)/255, (138+108*p)/255, 1)
                                return dotColor
                            }
                        }

                        Text {
                            id: elapsedText
                            anchors { right: closeBtn.left; rightMargin: Math.round(4 * island.sf); top: parent.top; topMargin: Math.round(14 * island.sf) }
                            text: elapsed
                            color: "#5e6678"
                            font { pixelSize: Math.round(10 * island.sf) }
                        }

                        Text {
                            id: sourceBadge
                            anchors { left: statusDot.right; leftMargin: Math.round(10 * island.sf); top: parent.top; topMargin: Math.round(17 * island.sf) }
                            text: source === "codex" ? "CX" : "CC"
                            color: source === "codex" ? "#7B9FFF" : "#FF8C42"
                            font { pixelSize: Math.round(9 * island.sf); bold: true }
                        }

                        Text {
                            anchors {
                                left: sourceBadge.right; leftMargin: Math.round(4 * island.sf)
                                right: elapsedText.left; rightMargin: Math.round(4 * island.sf)
                                top: parent.top; topMargin: Math.round(14 * island.sf)
                            }
                            text: cwdName
                            color: "#f2f4f8"
                            font { family: "Microsoft YaHei UI"; pixelSize: Math.round(13 * island.sf); bold: true }
                            elide: Text.ElideRight
                        }

                        Text {
                            anchors {
                                left: statusDot.right; leftMargin: Math.round(10 * island.sf)
                                right: closeBtn.left; rightMargin: Math.round(6 * island.sf)
                                bottom: parent.bottom; bottomMargin: Math.round(12 * island.sf)
                            }
                            text: lastPrompt
                            color: "#9aa3b5"
                            font { family: "Microsoft YaHei UI"; pixelSize: Math.round(11 * island.sf) }
                            elide: Text.ElideRight
                            maximumLineCount: 1
                        }

                        Item {
                            id: closeBtn
                            anchors { right: parent.right; rightMargin: Math.round(8 * island.sf); verticalCenter: parent.verticalCenter }
                            width: Math.round(30 * island.sf); height: Math.round(30 * island.sf)

                            HoverHandler { id: closeBtnHover }

                            Rectangle {
                                anchors.fill: parent
                                radius: width / 2
                                color: closeBtnHover.hovered ? "#3a3f50" : "transparent"
                                Behavior on color { ColorAnimation { duration: 120 } }
                            }

                            Text {
                                anchors.centerIn: parent
                                text: "×"
                                color: closeBtnHover.hovered ? "#e05c5c" : "#5e6678"
                                font { pixelSize: Math.round(18 * island.sf) }
                                Behavior on color { ColorAnimation { duration: 120 } }
                            }

                            TapHandler {
                                gesturePolicy: TapHandler.WithinBounds
                                onTapped: {
                                    if (cardDelegate._closing) return
                                    cardDelegate._closing = true
                                    closeTimer.start()
                                }
                            }
                        }

                        TapHandler {
                            acceptedButtons: Qt.LeftButton
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onDoubleTapped: bridge.jump(sid)
                        }
                    }
                }
            }

            Item {
                id: finishSurface
                z: 10
                visible: island.finishSurfaceActive && island.expanded
                opacity: visible ? 1.0 : 0.0
                anchors.fill: parent
                enabled: visible

                Behavior on opacity { NumberAnimation { duration: 140 } }

                Rectangle {
                    anchors {
                        fill: parent
                        margins: Math.round(8 * island.sf)
                    }
                    radius: Math.round(14 * island.sf)
                    color: island.notifyIsError ? "#241216" : "#102017"
                    border.width: 1
                    border.color: island.notifyIsError ? "#9f3d3d" : "#2f8f5b"

                    Rectangle {
                        id: finishIcon
                        width: Math.round(34 * island.sf)
                        height: width
                        radius: width / 2
                        anchors {
                            left: parent.left
                            leftMargin: Math.round(12 * island.sf)
                            verticalCenter: parent.verticalCenter
                        }
                        color: island.notifyIsError ? "#5d2525" : "#1d5a39"

                        Text {
                            anchors.centerIn: parent
                            text: island.notifyIsError ? "!" : "OK"
                            color: island.notifyIsError ? "#ffb3b3" : "#9ff0bf"
                            font {
                                family: "Microsoft YaHei UI"
                                pixelSize: Math.round((island.notifyIsError ? 18 : 10) * island.sf)
                                bold: true
                            }
                        }
                    }

                    Text {
                        id: finishTitle
                        anchors {
                            left: finishIcon.right
                            leftMargin: Math.round(12 * island.sf)
                            right: finishSourceBadge.left
                            rightMargin: Math.round(8 * island.sf)
                            top: parent.top
                            topMargin: Math.round(16 * island.sf)
                        }
                        text: island.notifyTitle
                        color: island.notifyIsError ? "#ffb3b3" : "#9ff0bf"
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        font {
                            family: "Microsoft YaHei UI"
                            pixelSize: Math.round(13 * island.sf)
                            bold: true
                        }
                    }

                    Rectangle {
                        id: finishSourceBadge
                        anchors {
                            right: parent.right
                            rightMargin: Math.round(12 * island.sf)
                            top: parent.top
                            topMargin: Math.round(15 * island.sf)
                        }
                        width: Math.round(34 * island.sf)
                        height: Math.round(20 * island.sf)
                        radius: Math.round(10 * island.sf)
                        color: island.notifySource === "codex" ? "#1b2748" : "#402719"

                        Text {
                            anchors.centerIn: parent
                            text: island.notifySource === "codex" ? "CX" : "CC"
                            color: island.notifySource === "codex" ? "#9cb8ff" : "#ffb16d"
                            font {
                                family: "Microsoft YaHei UI"
                                pixelSize: Math.round(10 * island.sf)
                                bold: true
                            }
                        }
                    }

                    Text {
                        id: finishCwd
                        anchors {
                            left: finishIcon.right
                            leftMargin: Math.round(12 * island.sf)
                            right: parent.right
                            rightMargin: Math.round(12 * island.sf)
                            top: finishTitle.bottom
                            topMargin: Math.round(7 * island.sf)
                        }
                        text: island.notifyCwdName.length > 0 ? island.notifyCwdName : "Session"
                        color: "#f2f4f8"
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        font {
                            family: "Microsoft YaHei UI"
                            pixelSize: Math.round(12 * island.sf)
                            bold: true
                        }
                    }

                    Text {
                        anchors {
                            left: finishIcon.right
                            leftMargin: Math.round(12 * island.sf)
                            right: parent.right
                            rightMargin: Math.round(12 * island.sf)
                            top: finishCwd.bottom
                            topMargin: Math.round(5 * island.sf)
                        }
                        text: island.notifyPrompt.length > 0 ? island.notifyPrompt : island.notifySid
                        color: "#9aa3b5"
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        font {
                            family: "Microsoft YaHei UI"
                            pixelSize: Math.round(11 * island.sf)
                        }
                    }
                }
            }
        }

        Timer {
            interval: 1000; running: true; repeat: true
            onTriggered: sessionsModel.refreshElapsed()
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onDoubleClicked: bridge.quit()
    }
}
