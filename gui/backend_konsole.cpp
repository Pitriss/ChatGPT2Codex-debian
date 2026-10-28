// Optional KDE Konsole KPart backend. Mirrors the documented KF6 Dolphin
// terminal-panel creation flow; never asks Konsole to start its own shell.
#include "backend_interface.h"
#include <KParts/ReadOnlyPart>
#include <KActionCollection>
#include <KXMLGUIClient>
#include <QAction>
#include <KPluginFactory>
#include <KPluginMetaData>
#include <kde_terminal_interface.h>
#include <QVBoxLayout>
#include <QFileInfo>
#include <QPointer>
#include <QKeySequence>
#include <KSharedConfig>
#include <KConfigGroup>

class KonsoleTerminalView final : public QWidget {
    Q_OBJECT
public:
    KonsoleTerminalView(QWidget *parent, const QString &program,
                        const QStringList &args, const QString &directory)
        : QWidget(parent), program_(program), args_(args) {
        Q_UNUSED(directory);
        auto *layout = new QVBoxLayout(this);
        layout->setContentsMargins(0, 0, 0, 0);
        // Use the same plugin identifier as Dolphin (KF6), not the old KF5 service.
        const auto result = KPluginFactory::loadFactory(KPluginMetaData(QStringLiteral("kf6/parts/konsolepart")));
        if (!result.plugin) { return; }
        // Konsole 25.04's hidden KPart tab bar adds nullptr for disabled
        // corner buttons (upstream e67e3226). Keep those hidden controls
        // present in this process. Empty flags explicitly exclude Persistent:
        // this never writes konsolerc or changes standalone Konsole windows.
        auto config = KSharedConfig::openConfig(QStringLiteral("konsolerc"));
        KConfigGroup tabBar(config, QStringLiteral("TabBar"));
        tabBar.writeEntry("SearchTabsButton", 0, KConfigBase::WriteConfigFlags{});
        tabBar.writeEntry("CloseTabButton", 1, KConfigBase::WriteConfigFlags{});
        part_ = result.plugin->create<KParts::ReadOnlyPart>(this);
        if (!part_) { return; }
        terminal_ = qobject_cast<TerminalInterface *>(part_);
        if (!terminal_ || !part_->widget()) {
            delete part_;
            part_ = nullptr;
            terminal_ = nullptr;
            return;
        }
        part_->widget()->setParent(this);
        layout->addWidget(part_->widget());
        // KPart's outer view manager is not the input surface. For keyboard
        // focus use the inner Konsole TerminalDisplay, as the main tab view
        // does on activation; retain the outer view as a safe fallback.
        QWidget *focusTarget = part_->widget();
        for (QWidget *child : part_->widget()->findChildren<QWidget *>()) {
            if (QString::fromLatin1(child->metaObject()->className())
                    .endsWith(QStringLiteral("TerminalDisplay"))) {
                focusTarget = child;
                break;
            }
        }
        setFocusProxy(focusTarget);
        reservePasteShortcuts(part_);
        connect(part_, &QObject::destroyed, this, [this] {
            part_ = nullptr;
            terminal_ = nullptr;
            Q_EMIT terminalFinished();
        });
    }
    ~KonsoleTerminalView() override {
        if (part_) {
            disconnect(part_, nullptr, this, nullptr);
            delete part_;
        }
    }
    bool ready() const { return part_ && terminal_; }
    // The embedded KPart owns the *native* Konsole paste QAction in its
    // SessionController child KXMLGUIClient, not in the outer main window.
    // Trigger it rather than sending clipboard bytes as shell input. Konsole
    // can then preserve its existing bracketed-paste and safety semantics.
    Q_INVOKABLE bool pasteClipboardText() {
        if (!part_ || !terminal_) { return false; }
        for (auto *client : part_->childClients()) {
            if (!client || !client->actionCollection()) { continue; }
            QAction *paste = client->actionCollection()->action(QStringLiteral("edit_paste"));
            if (paste && paste->isVisible() && paste->isEnabled()) {
                paste->trigger();
                return true;
            }
        }
        return false;
    }
    void startAttachedProcess() {
        if (!terminal_ || !QFileInfo(program_).isExecutable()) {
            Q_EMIT terminalFinished();
            return;
        }
        // Konsole Session::run() intentionally strips argv[0], unlike
        // QTermWidget::setArgs(). Prefix the verified program path or it
        // would silently lose the `screen` subcommand.
        QStringList fullArgs = args_;
        fullArgs.prepend(program_);
        terminal_->startProgram(program_, fullArgs);
        reservePasteShortcuts(part_);
    }
Q_SIGNALS:
    void terminalFinished();
private:
    void reservePasteShortcuts(KXMLGUIClient *client) {
        if (!client) { return; }
        if (auto *collection = client->actionCollection()) {
            for (QAction *action : collection->actions()) {
                if (action->property("g2cPasteShortcutsReserved").toBool()) { continue; }
                action->setProperty("g2cPasteShortcutsReserved", true);
                auto reserve = [action] {
                    auto shortcuts = action->shortcuts();
                    const bool removedV = shortcuts.removeAll(QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_V)) > 0;
                    const bool removedInsert = shortcuts.removeAll(QKeySequence(Qt::SHIFT | Qt::Key_Insert)) > 0;
                    if (removedV || removedInsert) { action->setShortcuts(shortcuts); }
                };
                // A shortcut/profile reload must not restore duplicate window
                // registrations. Leave the native QAction/menu operation intact.
                connect(action, &QAction::changed, this, reserve);
                reserve();
            }
        }
        for (auto *child : client->childClients()) { reservePasteShortcuts(child); }
    }

    QString program_;
    QStringList args_;
    QPointer<KParts::ReadOnlyPart> part_;
    TerminalInterface *terminal_ = nullptr;
};

class KonsoleBackend final : public QObject, public Gpt2CodexTerminalBackend {
    Q_OBJECT
    Q_PLUGIN_METADATA(IID GPT2CODEX_TERMINAL_BACKEND_IID)
    Q_INTERFACES(Gpt2CodexTerminalBackend)
public:
    QString id() const override { return QStringLiteral("konsole"); }
    bool usable() const override {
        return KPluginFactory::loadFactory(KPluginMetaData(QStringLiteral("kf6/parts/konsolepart"))).plugin != nullptr;
    }
    QWidget *create(QWidget *parent, const QString &program,
                    const QStringList &args, const QString &directory) override {
        auto *view = new KonsoleTerminalView(parent, program, args, directory);
        if (!view->ready()) { delete view; return nullptr; }
        return view;
    }
    void start(QWidget *view) override { static_cast<KonsoleTerminalView *>(view)->startAttachedProcess(); }
    // Konsole itself implements its color scheme, wallpaper and font.
    void refreshAppearance(QWidget *) override {}
};
#include "backend_konsole.moc"
