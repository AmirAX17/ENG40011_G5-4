CXX = g++
CXXFLAGS = -std=c++17 -Wall -Wextra -pthread

all: pc_server pi_client

pc_server: pc_server.cpp mock_processor.cpp processor.h
	$(CXX) $(CXXFLAGS) pc_server.cpp mock_processor.cpp -o pc_server

pi_client: pi_client.cpp
	$(CXX) $(CXXFLAGS) pi_client.cpp -o pi_client

clean:
	rm -f pc_server pi_client
