#pragma once
#include <QApplication>
#include <QKeyEvent>
#include <QWidget>
#include <functional>

// Application filters run before TerminalDisplay's ShortcutOverride handler.
// Claim only paste keys inside the selected terminal, then invoke the very
// same QAction as the Edit menu. KPart/window shortcut duplicates cannot race.
class PasteShortcutFilter final : public QObject {
public:
    PasteShortcutFilter(QObject *parent, std::function<bool(QWidget *)> accepts,
                        std::function<void()> paste)
        : QObject(parent), accepts_(std::move(accepts)), paste_(std::move(paste)) {
        qApp->installEventFilter(this);
    }
protected:
    bool eventFilter(QObject *target, QEvent *event) override {
        if (event->type() != QEvent::ShortcutOverride && event->type() != QEvent::KeyPress) {
            return false;
        }
        auto *key = static_cast<QKeyEvent *>(event);
        const auto modifiers = key->modifiers();
        const bool paste = (key->key() == Qt::Key_V && modifiers == (Qt::ControlModifier | Qt::ShiftModifier))
            || (key->key() == Qt::Key_Insert && modifiers == Qt::ShiftModifier);
        auto *widget = qobject_cast<QWidget *>(target);
        if (!paste || !widget || !accepts_(widget)) { return false; }
        event->accept();
        if (event->type() == QEvent::KeyPress && !key->isAutoRepeat()) { paste_(); }
        return true;
    }
private:
    std::function<bool(QWidget *)> accepts_;
    std::function<void()> paste_;
};
