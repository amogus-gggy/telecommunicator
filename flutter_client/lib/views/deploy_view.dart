import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../state/app_state.dart';
import '../ui/theme.dart';

class DeployView extends StatefulWidget {
  const DeployView({super.key, required this.state});
  final AppState state;

  @override
  State<DeployView> createState() => _DeployViewState();
}

class _DeployViewState extends State<DeployView> {
  final _hostCtrl = TextEditingController();
  final _portCtrl = TextEditingController(text: '22');
  final _userCtrl = TextEditingController(text: 'root');
  final _passwordCtrl = TextEditingController();
  final _keyCtrl = TextEditingController();
  final _publicPortCtrl = TextEditingController(text: '8000');
  final _addressCtrl = TextEditingController();
  bool _useKey = false;
  bool _busy = false;
  final List<String> _log = [];
  String? _resultUrl;

  void _appendLog(String line) {
    if (!mounted) return;
    setState(() => _log.add(line));
  }

  String _setupScript({
    required String secretKey,
    required String serverAddress,
    required int publicPort,
  }) {
    return """
set -euo pipefail
echo "[1/4] Checking docker..."
if ! command -v docker >/dev/null 2>&1; then
  apt-get update && apt-get install -y curl
  curl -fsSL https://get.docker.com | sh
fi
echo "[2/4] Configuration..."
echo "[3/4] Pulling and starting the container..."
docker rm -f telecommunicator >/dev/null 2>&1 || true
docker pull ghcr.io/amogus-gggy/telecommunicator:latest
docker run -d --name telecommunicator --restart unless-stopped \\
  -p $publicPort:8000 \\
  -e SECRET_KEY=$secretKey \\
  -e SERVER_ADDRESS=$serverAddress \\
  -e DATABASE_URL=sqlite+aiosqlite:////data/messenger.db \\
  -v td_data:/data \\
  -v td_uploads:/app/uploads \\
  ghcr.io/amogus-gggy/telecommunicator:latest
echo "[4/4] Telecommunicator is running on port $publicPort"
""";
  }

  Future<void> _deploy() async {
    final host = _hostCtrl.text.trim();
    final port = int.tryParse(_portCtrl.text.trim()) ?? 22;
    final user = _userCtrl.text.trim();
    final publicPort = int.tryParse(_publicPortCtrl.text.trim()) ?? 8000;
    final serverAddress = _addressCtrl.text.trim().isNotEmpty
        ? _addressCtrl.text.trim()
        : '$host:$publicPort';

    if (host.isEmpty || user.isEmpty) {
      showSnack(context, 'Fill in host and user', ok: false);
      return;
    }

    setState(() {
      _busy = true;
      _log.clear();
      _resultUrl = null;
    });

    SSHClient? ssh;
    try {
      _appendLog('Connecting to $user@$host:$port ...');
      final socket = await SSHSocket.connect(host, port,
          timeout: const Duration(seconds: 20));
      ssh = SSHClient(
        socket,
        username: user,
        onPasswordRequest: _useKey ? null : () => _passwordCtrl.text,
        identities: _useKey && _keyCtrl.text.trim().isNotEmpty
            ? SSHKeyPair.fromPem(_keyCtrl.text.trim())
            : [],
      );
      _appendLog('Connected. Running setup...');

      final secret = List<int>.generate(32, (_) => Random.secure().nextInt(256))
          .map((b) => b.toRadixString(16).padLeft(2, '0'))
          .join();
      final script =
          _setupScript(secretKey: secret, serverAddress: serverAddress, publicPort: publicPort);

      final session = await ssh.execute('bash -s');
      session.stdin.add(utf8.encode(script));
      await session.stdin.close();
      final outDone = Completer<void>();
      final errDone = Completer<void>();
      session.stdout
          .cast<List<int>>()
          .transform(utf8.decoder)
          .listen((chunk) {
        for (final line in const LineSplitter().convert(chunk)) {
          _appendLog(line);
        }
      }, onDone: () => outDone.complete());
      session.stderr
          .cast<List<int>>()
          .transform(utf8.decoder)
          .listen((chunk) {
        for (final line in const LineSplitter().convert(chunk)) {
          _appendLog('! $line');
        }
      }, onDone: () => errDone.complete());
      await Future.wait([outDone.future, errDone.future]);
      await session.done;

      final exit = session.exitCode;
      if (exit != 0) {
        throw 'Setup script failed with exit code $exit';
      }
      if (!mounted) return;
      setState(() {
        _busy = false;
        _resultUrl = 'http://$serverAddress';
      });
      _appendLog('Server deployed at $_resultUrl');
    } catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      _appendLog('ERROR: $e');
    } finally {
      ssh?.close();
    }
  }

  Future<void> _useDeployedServer() async {
    if (_resultUrl == null) return;
    final api = _resultUrl!;
    final ws = '${api.replaceFirst(RegExp(r'^http'), 'ws')}/ws';
    final st = widget.state;
    st.apiUrl = api;
    st.wsUrl = ws;
    await st.settings?.set('settings.api_url', api);
    await st.settings?.set('settings.ws_url', ws);
    await closeSharedClients();
    if (!mounted) return;
    showSnack(context, 'Server address saved. Sign in to continue.');
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Deploy to my VPS')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Enter your VPS credentials — the server will be set up '
                'automatically (Ubuntu/Debian, Docker).',
                style: TextStyle(color: context.onSurfaceVariant)),
            const SizedBox(height: 12),
            TextField(
                controller: _hostCtrl,
                decoration:
                    themedFieldDecoration(label: 'VPS host (IP or domain)')),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(
                  child: TextField(
                      controller: _portCtrl,
                      keyboardType: TextInputType.number,
                      decoration: themedFieldDecoration(label: 'SSH port'))),
              const SizedBox(width: 8),
              Expanded(
                  child: TextField(
                      controller: _userCtrl,
                      decoration: themedFieldDecoration(label: 'SSH user'))),
            ]),
            const SizedBox(height: 8),
            Row(children: [
              ChoiceChip(
                label: const Text('Password'),
                selected: !_useKey,
                onSelected: (_) => setState(() => _useKey = false),
              ),
              const SizedBox(width: 8),
              ChoiceChip(
                label: const Text('Private key'),
                selected: _useKey,
                onSelected: (_) => setState(() => _useKey = true),
              ),
            ]),
            const SizedBox(height: 8),
            if (_useKey)
              TextField(
                  controller: _keyCtrl,
                  maxLines: 6,
                  decoration: themedFieldDecoration(
                      label: 'Private key (PEM)'))
            else
              TextField(
                  controller: _passwordCtrl,
                  obscureText: true,
                  decoration:
                      themedFieldDecoration(label: 'SSH password')),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(
                  child: TextField(
                      controller: _publicPortCtrl,
                      keyboardType: TextInputType.number,
                      decoration:
                          themedFieldDecoration(label: 'Public port'))),
              const SizedBox(width: 8),
              Expanded(
                  child: TextField(
                      controller: _addressCtrl,
                      decoration: themedFieldDecoration(
                          label: 'Public address (optional)',
                          hintText: 'host:8000'))),
            ]),
            const SizedBox(height: 16),
            primaryButton(context, 'Deploy server',
                onPressed: _busy ? null : _deploy),
            if (_resultUrl != null) ...[
              const SizedBox(height: 12),
              primaryButton(context, 'Connect to $_resultUrl',
                  onPressed: _useDeployedServer),
            ],
            const SizedBox(height: 16),
            if (_log.isNotEmpty)
              Container(
                height: 260,
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.black,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: ListView.builder(
                  itemCount: _log.length,
                  itemBuilder: (_, i) => Text(_log[i],
                      style: const TextStyle(
                          color: Colors.greenAccent,
                          fontFamily: 'monospace',
                          fontSize: 12)),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
