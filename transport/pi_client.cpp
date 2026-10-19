#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>

constexpr int PORT = 5050;
constexpr int SEND_INTERVAL_SECONDS = 10;

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

std::string read_new_text(
    const std::string& filename,
    std::streamoff& last_position
) {
    std::ifstream file(filename, std::ios::binary);

    if (!file.is_open()) {
        return "";
    }

    file.seekg(0, std::ios::end);
    std::streamoff file_size = file.tellg();

    // If Whisper/new session replaces the file, start again.
    if (file_size < last_position) {
        last_position = 0;
    }

    if (file_size == last_position) {
        return "";
    }

    file.seekg(last_position);

    std::string new_text(
        (std::istreambuf_iterator<char>(file)),
        std::istreambuf_iterator<char>()
    );

    last_position = file_size;

    return new_text;
}

int main(int argc, char* argv[]) {
    std::string server_ip = "127.0.0.1";

    if (argc >= 2) {
        server_ip = argv[1];
    }

    const std::string transcript_file = "transport/transcript.txt";
    const std::string output_file = "transport/llm_output.txt";

    int socket_fd = socket(AF_INET, SOCK_STREAM, 0);

    if (socket_fd < 0) {
        std::cerr << "Failed to create socket.\n";
        return 1;
    }

    sockaddr_in server_address{};
    server_address.sin_family = AF_INET;
    server_address.sin_port = htons(PORT);

    if (
        inet_pton(
            AF_INET,
            server_ip.c_str(),
            &server_address.sin_addr
        ) <= 0
    ) {
        std::cerr << "Invalid server IP address.\n";
        close(socket_fd);
        return 1;
    }

    std::cout << "Connecting to " << server_ip
              << ":" << PORT << "...\n";

    if (
        connect(
            socket_fd,
            reinterpret_cast<sockaddr*>(&server_address),
            sizeof(server_address)
        ) < 0
    ) {
        std::cerr << "Could not connect to PC server.\n";
        close(socket_fd);
        return 1;
    }

    std::cout << "Connected.\n";
    std::cout << "Watching: " << transcript_file << "\n";
    std::cout << "Sending new transcript text every "
              << SEND_INTERVAL_SECONDS << " seconds.\n";
    std::cout << "Press ENTER when the patient/session is finished.\n\n";

    std::atomic<bool> end_requested(false);

    std::thread keyboard_thread([&]() {
        std::string input;
        std::getline(std::cin, input);
        end_requested = true;
    });

    std::streamoff last_position = 0;

    while (!end_requested) {
        std::this_thread::sleep_for(
            std::chrono::seconds(SEND_INTERVAL_SECONDS)
        );

        std::string chunk = read_new_text(
            transcript_file,
            last_position
        );

        if (chunk.empty()) {
            std::cout << "[No new transcript text]\n";
            continue;
        }

        std::cout << "\n[Sending new chunk]\n";
        std::cout << chunk << "\n";

        if (!send_message(socket_fd, chunk)) {
            std::cerr << "Failed to send transcript chunk.\n";
            break;
        }

        std::string response;

        if (!receive_message(socket_fd, response)) {
            std::cerr << "Server connection lost.\n";
            break;
        }

        if (!response.empty()) {
            std::cout << "\n[AI response]\n";
            std::cout << response << "\n";

            std::ofstream output(output_file);
            output << response;
            output.close();

            std::cout << "Saved to: " << output_file << "\n";
        } else {
            std::cout << "[No contradiction returned]\n";
        }
    }

    // Send anything written since the previous 10-second check.
    std::string final_chunk = read_new_text(
        transcript_file,
        last_position
    );

    if (!final_chunk.empty()) {
        std::cout << "\n[Sending final chunk]\n";
        std::cout << final_chunk << "\n";

        send_message(socket_fd, final_chunk);

        std::string response;

        if (receive_message(socket_fd, response) &&
            !response.empty()) {

            std::cout << "\n[AI response]\n";
            std::cout << response << "\n";

            std::ofstream output(output_file);
            output << response;
        }
    }

    std::cout << "\nEnding session...\n";

    send_message(socket_fd, END_SESSION);

    std::string final_response;

    if (receive_message(socket_fd, final_response)) {
        std::cout << "Server: " << final_response << "\n";
    }

    close(socket_fd);

    if (keyboard_thread.joinable()) {
        keyboard_thread.join();
    }

    std::cout << "Client closed.\n";

    return 0;
}
