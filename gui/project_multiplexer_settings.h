// Project preference edits are independent of terminal/backend lifecycle.
// This widget only probes, reads project preferences, and saves one preference.
#pragma once

class ProjectMultiplexerSettings final : public QGroupBox {
public:
    explicit ProjectMultiplexerSettings(const Options &options, QWidget *parent = nullptr, bool load = true)
        : QGroupBox(QStringLiteral("Multiplexer projektu"), parent), options_(options) {
        auto *form = new QFormLayout(this);
        projects_ = new QComboBox(this);
        projects_->setObjectName(QStringLiteral("multiplexerProject"));
        mux_ = new QComboBox(this);
        mux_->setObjectName(QStringLiteral("projectMultiplexer"));
        mux_->addItem(QStringLiteral("GNU screen (výchozí)"), QStringLiteral("screen"));
        mux_->addItem(QStringLiteral("tmux"), QStringLiteral("tmux"));
        save_ = new QPushButton(QStringLiteral("Uložit preferenci projektu"), this);
        save_->setObjectName(QStringLiteral("saveProjectMultiplexer"));
        note_ = new QLabel(this);
        note_->setWordWrap(true);
        form->addRow(QStringLiteral("Projekt:"), projects_);
        form->addRow(QStringLiteral("Preferovaný multiplexer:"), mux_);
        form->addRow(save_);
        form->addRow(note_);
        setAvailable(false, false);
        connect(projects_, qOverload<int>(&QComboBox::currentIndexChanged), this, [this] {
            mux_->setCurrentIndex(qMax(0, mux_->findData(preferences_.value(projects_->currentData().toString(), QStringLiteral("screen")))));
            updateDirty();
        });
        connect(mux_, qOverload<int>(&QComboBox::currentIndexChanged), this, [this] { updateDirty(); });
        connect(save_, &QPushButton::clicked, this, [this] { save(); });
        if (load) { QTimer::singleShot(0, this, [this] { reload(); }); }
    }
    ~ProjectMultiplexerSettings() override {
        if (process_) { process_->kill(); process_->waitForFinished(1000); }
    }

    // Strict metadata-only parsers also used by isolated GUI tests.
    bool loadProjects(const QByteArray &raw) {
        if (raw.size() > 16384 || raw.contains('\0')) { return false; }
        static const QRegularExpression line(QStringLiteral(R"(^project_id=([a-z0-9_-]{1,64}) preferred=(screen|tmux)$)"));
        QHash<QString, QString> parsed;
        for (const QString &value : QString::fromUtf8(raw).split(QLatin1Char('\n'), Qt::SkipEmptyParts)) {
            const auto match = line.match(value);
            if (!match.hasMatch() || parsed.contains(match.captured(1)) || parsed.size() >= 64) { return false; }
            parsed.insert(match.captured(1), match.captured(2));
        }
        if (parsed.isEmpty()) { return false; }
        preferences_ = parsed;
        const QSignalBlocker block(projects_);
        projects_->clear();
        QStringList ids = preferences_.keys();
        ids.sort();
        for (const QString &id : ids) { projects_->addItem(id, id); }
        mux_->setCurrentIndex(qMax(0, mux_->findData(preferences_.value(projects_->currentData().toString()))));
        updateDirty();
        return true;
    }
    void setAvailable(bool screen, bool tmux) {
        screenAvailable_ = screen;
        tmuxAvailable_ = tmux;
        auto *model = qobject_cast<QStandardItemModel *>(mux_->model());
        for (int index = 0; index < 2; ++index) {
            const bool available = index == 0 ? screen : tmux;
            model->item(index)->setEnabled(available);
            model->item(index)->setToolTip(available ? QString() : QStringLiteral("Program není dostupný nebo jej nelze spustit. Ověř instalaci a PATH. Aplikace jej neinstaluje a nepoužije náhradu."));
        }
        note_->setText(QStringLiteral("Platí pouze pro příští explicitně schválený start. Existující relace si ponechají svůj multiplexer. %1")
            .arg(tmux ? QString() : QStringLiteral("tmux není dostupný nebo jej nelze spustit; jeho volba je zakázaná.")));
        updateDirty();
    }
private:
    void updateDirty() {
        const QString id = projects_->currentData().toString();
        const QString mux = mux_->currentData().toString();
        const bool available = mux == QStringLiteral("screen") ? screenAvailable_ : tmuxAvailable_;
        projects_->setEnabled(!process_ && !preferences_.isEmpty());
        mux_->setEnabled(!process_ && !preferences_.isEmpty());
        save_->setEnabled(!process_ && !id.isEmpty() && available && preferences_.value(id) != mux);
    }
    void run(QStringList args, std::function<void(bool, const QByteArray &)> done) {
        if (process_) { return; }
        if (!options_.config.isEmpty()) { args << QStringLiteral("--config") << options_.config; }
        auto *proc = new QProcess(this);
        process_ = proc;
        proc->setProcessChannelMode(QProcess::SeparateChannels);
        updateDirty();
        auto finish = [this, proc, done](bool ok) {
            if (process_ != proc) { return; }
            process_ = nullptr;
            const QByteArray raw = proc->readAllStandardOutput();
            proc->deleteLater();
            done(ok, raw);
            updateDirty();
        };
        connect(proc, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
            [finish](int code, QProcess::ExitStatus status) { finish(code == 0 && status == QProcess::NormalExit); });
        connect(proc, &QProcess::errorOccurred, this, [finish](QProcess::ProcessError) { finish(false); });
        proc->start(options_.bridgeCli, args);
        QTimer::singleShot(5000, proc, [this, proc] { if (process_ == proc) { proc->kill(); } });
    }
    void reload() {
        run({QStringLiteral("session"), QStringLiteral("projects")}, [this](bool ok, const QByteArray &raw) {
            if (!ok || !loadProjects(raw)) { note_->setText(QStringLiteral("Preference projektů nelze bezpečně načíst.")); return; }
            run({QStringLiteral("session"), QStringLiteral("probe")}, [this](bool ok, const QByteArray &raw) {
                static const QRegularExpression format(QStringLiteral("^multiplexer=screen available=([01])\\nmultiplexer=tmux available=([01])\\n$"));
                const auto match = format.match(QString::fromUtf8(raw));
                setAvailable(ok && match.hasMatch() && match.captured(1) == QStringLiteral("1"),
                    ok && match.hasMatch() && match.captured(2) == QStringLiteral("1"));
            });
        });
    }
    void save() {
        const QString id = projects_->currentData().toString(), mux = mux_->currentData().toString();
        if (!save_->isEnabled()) { return; }
        run({QStringLiteral("session"), QStringLiteral("prefer"), QStringLiteral("--id"), id,
            QStringLiteral("--multiplexer"), mux}, [this, id, mux](bool ok, const QByteArray &raw) {
            const QByteArray expected = QStringLiteral("project_id=%1 preferred=%2\n").arg(id, mux).toUtf8();
            if (ok && raw == expected) {
                preferences_[id] = mux;
                note_->setText(QStringLiteral("Preference projektu uložena. Běžící relace pokračují beze změny; žádná nová relace nebyla spuštěna."));
            } else { note_->setText(QStringLiteral("Preferenci nelze uložit. Žádná relace nebyla spuštěna ani přepnuta.")); }
        });
    }
    Options options_;
    QComboBox *projects_ = nullptr, *mux_ = nullptr;
    QPushButton *save_ = nullptr;
    QLabel *note_ = nullptr;
    QProcess *process_ = nullptr;
    QHash<QString, QString> preferences_;
    bool screenAvailable_ = false, tmuxAvailable_ = false;
};
