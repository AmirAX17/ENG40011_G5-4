#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <string>

constexpr int PORT = 5050;
const std::string END_SESSION = "__END_SESSION__";

bool send_all(int socket_fd, const void* data, size_t length) {
    const char* buffer = static_cast<const char*>(data);

    while (length > 0) {
        ssize_t sent = send(socket_fd, buffer, length, 0);

        if (sent <= 0) {
            return false;
        }

        buffer += sent;
        length -= static_cast<size_t>(sent);
    }

    return true;
}

bool receive_all(int socket_fd, void* data, size_t length) {
    char* buffer = static_cast<char*>(data);

    while (length > 0) {
        ssize_t received = recv(socket_fd, buffer, length, 0);

        if (received <= 0) {
            return false;
        }

        buffer += received;
        length -= static_cast<size_t>(received);
    }

    return true;
}

bool send_message(int socket_fd, const std::string& message) {
    uint32_t length = htonl(static_cast<uint32_t>(message.size()));

    if (!send_all(socket_fd, &length, sizeof(length))) {
        return false;
    }

    if (!message.empty()) {
        return send_all(socket_fd, message.data(), message.size());
    }

    return true;
}

bool receive_message(int socket_fd, std::string& message) {
    uint32_t network_length;

    if (!receive_all(socket_fd, &network_length, sizeof(network_length))) {
        return false;
    }

    uint32_t length = ntohl(network_length);

    message.resize(length);

    if (length > 0) {
        return receive_all(socket_fd, message.data(), length);
    }

    return true;
}

std::string lowercase(std::string text) {
    std::transform(
        text.begin(),
        text.end(),
        text.begin(),
        [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        }
    );

    return text;
}

/*
    TEMPORARY MOCK PROCESSOR

    This will later be replaced by the Qwen3/Ollama processing layer.

    For now it gives us something predictable to test:
    if an earlier chunk says "no known allergies"
    and a later chunk says "allergic to penicillin",
    the server returns a warning.
*/
std::string process_chunk(
    const std::string& previous_context,
    const std::string& new_chunk
) {
    std::string old_text = lowercase(previous_context);
    std::string new_text = lowercase(new_chunk);

    if (
        old_text.find("no known allergies") != std::string::npos &&
        new_text.find("allergic to penicillin") != std::string::npos
    ) {
        return "WARNING: Contradiction detected. Earlier information stated "
               "no known allergies, but the latest transcript reports a "
               "penicillin allergy.";
    }

    return "";
}

int main() {
    int server_socket = socket(AF_INET, SOCK_STREAM, 0);

    if (server_socket < 0) {
        std::cerr << "Failed to create socket.\n";
        return 1;
    }

    int reuse = 1;
    setsockopt(
        server_socket,
        SOL_SOCKET,
        SO_REUSEADDR,
        &reuse,
        sizeof(reuse)
    );

    sockaddr_in server_address{};
    server_address.sin_family = AF_INET;
    server_address.sin_addr.s_addr = INADDR_ANY;
    server_address.sin_port = htons(PORT);

    if (
        bind(
            server_socket,
            reinterpret_cast<sockaddr*>(&server_address),
            sizeof(server_address)
        ) < 0
    ) {
        std::cerr << "Failed to bind to port " << PORT << ".\n";
        close(server_socket);
        return 1;
    }

    if (listen(server_socket, 1) < 0) {
        std::cerr << "Failed to listen for connections.\n";
        close(server_socket);
        return 1;
    }

    std::cout << "Second Observer PC server\n";
    std::cout << "Listening on TCP port " << PORT << "...\n";

    sockaddr_in client_address{};
    socklen_t client_length = sizeof(client_address);

    int client_socket = accept(
        server_socket,
        reinterpret_cast<sockaddr*>(&client_address),
        &client_length
    );

    if (client_socket < 0) {
        std::cerr << "Failed to accept client connection.\n";
        close(server_socket);
        return 1;
    }

    char client_ip[INET_ADDRSTRLEN];

    inet_ntop(
        AF_INET,
        &client_address.sin_addr,
        client_ip,
        sizeof(client_ip)
    );

    std::cout << "Client connected from " << client_ip << "\n\n";

    std::string full_transcript;

    while (true) {
        std::string chunk;

        if (!receive_message(client_socket, chunk)) {
            std::cout << "Client disconnected.\n";
            break;
        }

        if (chunk == END_SESSION) {
            std::cout << "\n--- END OF SESSION ---\n";
            std::cout << "Full accumulated transcript:\n";
            std::cout << full_transcript << "\n";

            send_message(client_socket, "SESSION_COMPLETE");
            break;
        }

        std::cout << "[Received chunk]\n";
        std::cout << chunk << "\n\n";

        std::string response = process_chunk(
            full_transcript,
            chunk
        );

        if (!full_transcript.empty()) {
            full_transcript += "\n";
        }

        full_transcript += chunk;

        if (!response.empty()) {
            std::cout << "[Mock warning]\n";
            std::cout << response << "\n\n";
        }

        // Empty response means there is nothing for the Pi to say.
        send_message(client_socket, response);
    }

    close(client_socket);
    close(server_socket);

    return 0;
}
