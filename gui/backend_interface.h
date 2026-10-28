#pragma once
// Qt-only ABI used by each separately packaged GUI terminal backend.
// Each plugin provides a QWidget that emits terminalFinished() and owns exactly
// one transient bridge CLI attachment process, never a GNU screen server.
#include <QString>
#include <QStringList>
#include <QWidget>

class Gpt2CodexTerminalBackend {
public:
    virtual ~Gpt2CodexTerminalBackend() = default;
    virtual QString id() const = 0;
    virtual bool usable() const = 0;
    virtual QWidget *create(QWidget *parent, const QString &program,
                            const QStringList &args, const QString &directory) = 0;
    virtual void start(QWidget *view) = 0;
    virtual void refreshAppearance(QWidget *view) = 0;
};
#define GPT2CODEX_TERMINAL_BACKEND_IID "cz.chytrex.gpt2codex.TerminalBackend/1.0"
Q_DECLARE_INTERFACE(Gpt2CodexTerminalBackend, GPT2CODEX_TERMINAL_BACKEND_IID)
